import json
import tempfile
import unittest
from pathlib import Path

from app import db
from app.fsm import NodeState
from app.llm import FakeModelClient
from app.orchestrator import WorkerConfig, run_to_completion, start_run
from app.search import FakeSearchProvider, SourceMaterial
from app.schemas import DeepDiveOutput, ReflectOutput, ScopeOutput


class FailingExtractionModel(FakeModelClient):
    def extract_findings(self, analysis: str):
        self._record("extract_findings", {"analysis": analysis})
        raise RuntimeError("extract failed")


def thread_candidate(
    *,
    topic: str = "Child thread",
    priority: int = 1,
    material: bool = True,
    resolution_state: str = "unresolved_investigable",
    evidence_basis: str = "direct",
) -> dict:
    return {
        "topic": topic,
        "description": f"Description for {topic}.",
        "material": material,
        "priority": priority,
        "resolution_state": resolution_state,
        "evidence_basis": evidence_basis,
        "investigation_brief": f"Investigate {topic}.",
    }


class OrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "research.sqlite"
        self.conn = db.connect(self.db_path)
        db.initialize_database(self.conn)

    def tearDown(self):
        self.conn.close()
        self.temp_dir.cleanup()

    def test_start_run_seeds_root_nodes_from_scope(self):
        scope = ScopeOutput.model_validate(
            {
                "root_threads": [
                    {
                        "topic": "Revenue quality",
                        "description": "Assess revenue quality.",
                        "priority": 1,
                        "investigation_brief": "Investigate revenue quality.",
                    },
                    {
                        "topic": "Customer concentration",
                        "description": "Assess customer concentration.",
                        "priority": 2,
                        "investigation_brief": "Investigate customers.",
                    },
                ]
            }
        )
        model = FakeModelClient(scope_outputs=[scope])

        run = start_run(self.conn, company="Example Co", model=model)

        roots = db.root_nodes(self.conn, run.run_id)
        self.assertEqual(["Revenue quality", "Customer concentration"], [
            node.topic for node in roots
        ])
        self.assertEqual([NodeState.PENDING, NodeState.PENDING], [
            node.status for node in roots
        ])

    def test_leaf_node_run_completes(self):
        model = FakeModelClient()

        run = start_run(self.conn, company="Example Co", model=model)
        completed = run_to_completion(self.conn, run_id=run.run_id, model=model)

        self.assertEqual("complete", completed.status)
        root = db.root_nodes(self.conn, run.run_id)[0]
        self.assertEqual(NodeState.COMPLETE, root.status)
        self.assertIn("Fake analysis", root.analysis)
        self.assertEqual(
            {
                "scope": 1,
                "deep_dive": 1,
                "extract_findings": 1,
                "reflect": 1,
            },
            model.call_counts(),
        )

    def test_worker_passes_search_results_to_deep_dive(self):
        model = FakeModelClient()
        search_provider = FakeSearchProvider([
            SourceMaterial(
                title="Annual report excerpt",
                url=None,
                source_type="primary_filing",
                published_at=None,
                text="Example Co revenue details.",
            )
        ])

        run = start_run(self.conn, company="Example Co", model=model)
        run_to_completion(
            self.conn,
            run_id=run.run_id,
            model=model,
            search_provider=search_provider,
        )

        self.assertEqual(5, search_provider.calls[0]["max_results"])
        deep_dive_call = [
            call for call in model.calls if call.call_type == "deep_dive"
        ][0]
        self.assertEqual(1, deep_dive_call.payload["source_material_count"])

    def test_internal_node_synthesizes_after_child_completes(self):
        root_reflect = ReflectOutput.model_validate(
            {"child_threads": [thread_candidate(topic="Margin durability")]}
        )
        child_reflect = ReflectOutput.model_validate({"child_threads": []})
        model = FakeModelClient(
            reflect_outputs=[root_reflect, child_reflect],
            branch_syntheses=["Root synthesis."],
        )

        run = start_run(self.conn, company="Example Co", model=model)
        completed = run_to_completion(self.conn, run_id=run.run_id, model=model)

        self.assertEqual("complete", completed.status)
        root = db.root_nodes(self.conn, run.run_id)[0]
        children = db.child_nodes(self.conn, root.node_id)

        self.assertEqual(NodeState.COMPLETE, root.status)
        self.assertEqual("Root synthesis.", root.branch_synthesis)
        self.assertEqual(1, len(children))
        self.assertEqual(NodeState.COMPLETE, children[0].status)
        self.assertEqual(1, model.calls[-1].payload["child_summary_count"])

    def test_discovered_threads_become_siblings(self):
        first_deep_dive = DeepDiveOutput.model_validate(
            {
                "analysis": "Root analysis. END_OF_DEEP_DIVE_ANALYSIS.",
                "abstract": "Root abstract.",
                "discovered_threads": [
                    thread_candidate(topic="Discovered sibling")
                ],
            }
        )
        second_deep_dive = DeepDiveOutput.model_validate(
            {
                "analysis": "Sibling analysis. END_OF_DEEP_DIVE_ANALYSIS.",
                "abstract": "Sibling abstract.",
            }
        )
        model = FakeModelClient(
            deep_dive_outputs=[first_deep_dive, second_deep_dive],
            reflect_outputs=[
                ReflectOutput.model_validate({"child_threads": []}),
                ReflectOutput.model_validate({"child_threads": []}),
            ],
        )

        run = start_run(self.conn, company="Example Co", model=model)
        run_to_completion(self.conn, run_id=run.run_id, model=model)

        roots = db.root_nodes(self.conn, run.run_id)
        first_root_children = db.child_nodes(self.conn, roots[0].node_id)

        self.assertEqual(["Example Co business overview", "Discovered sibling"], [
            node.topic for node in roots
        ])
        self.assertEqual([], first_root_children)

    def test_depth_cap_prevents_child_spawn(self):
        root_reflect = ReflectOutput.model_validate(
            {"child_threads": [thread_candidate(topic="Too deep")]}
        )
        model = FakeModelClient(reflect_outputs=[root_reflect])

        run = start_run(self.conn, company="Example Co", model=model)
        run_to_completion(
            self.conn,
            run_id=run.run_id,
            model=model,
            config=WorkerConfig(max_depth=0),
        )

        root = db.root_nodes(self.conn, run.run_id)[0]
        self.assertEqual(NodeState.COMPLETE, root.status)
        self.assertEqual([], db.child_nodes(self.conn, root.node_id))

    def test_max_total_nodes_caps_spawned_children(self):
        root_reflect = ReflectOutput.model_validate(
            {
                "child_threads": [
                    thread_candidate(topic="First child"),
                    thread_candidate(topic="Second child"),
                ]
            }
        )
        model = FakeModelClient(
            reflect_outputs=[
                root_reflect,
                ReflectOutput.model_validate({"child_threads": []}),
            ],
            branch_syntheses=["Root synthesis."],
        )

        run = start_run(self.conn, company="Example Co", model=model)
        run_to_completion(
            self.conn,
            run_id=run.run_id,
            model=model,
            config=WorkerConfig(max_total_nodes=2),
        )

        root = db.root_nodes(self.conn, run.run_id)[0]
        self.assertEqual(["First child"], [
            child.topic for child in db.child_nodes(self.conn, root.node_id)
        ])

    def test_worker_persists_model_calls_for_leaf_run(self):
        model = FakeModelClient()

        run = start_run(
            self.conn,
            company="Example Co",
            model=model,
            config=WorkerConfig(model_name="fake-gemma", prompt_version="test-v1"),
        )
        run_to_completion(
            self.conn,
            run_id=run.run_id,
            model=model,
            config=WorkerConfig(model_name="fake-gemma", prompt_version="test-v1"),
        )

        calls = db.model_calls(self.conn, run_id=run.run_id)

        self.assertEqual(
            ["scope", "deep_dive", "extract_findings", "reflect"],
            [call.call_type for call in calls],
        )
        self.assertIsNone(calls[0].node_id)
        self.assertEqual("fake-gemma", calls[0].model_name)
        self.assertEqual("test-v1", calls[0].prompt_version)
        self.assertEqual({"company": "Example Co"}, json.loads(calls[0].input_json))
        self.assertIn("root_threads", json.loads(calls[0].output_json))

        node_calls = calls[1:]
        self.assertTrue(all(call.node_id for call in node_calls))
        self.assertIn("analysis", json.loads(calls[1].output_json))
        self.assertIn("analysis", json.loads(calls[2].input_json))

    def test_extraction_failure_is_recorded_and_non_fatal(self):
        model = FailingExtractionModel()

        run = start_run(self.conn, company="Example Co", model=model)
        completed = run_to_completion(self.conn, run_id=run.run_id, model=model)

        calls = db.model_calls(self.conn, run_id=run.run_id)
        extract_call = [
            call for call in calls if call.call_type == "extract_findings"
        ][0]

        self.assertEqual("complete", completed.status)
        self.assertEqual("extract failed", extract_call.error)
        self.assertIsNone(extract_call.output_json)


if __name__ == "__main__":
    unittest.main()
