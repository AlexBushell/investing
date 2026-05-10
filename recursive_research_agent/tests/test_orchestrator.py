import json
import tempfile
import unittest
from pathlib import Path

from app import db
from app.fsm import NodeEvent, NodeState
from app.llm import FakeModelClient
from app.orchestrator import WorkerConfig, run_to_completion, start_run
from app.search import FakeSearchProvider, SourceMaterial
from app.schemas import (
    DedupDecision,
    DeduplicationDecisionOutput,
    DeepDiveOutput,
    ReflectOutput,
    ScopeOutput,
    SearchPlanOutput,
    SiblingConsolidationOutput,
)


class FailingExtractionModel(FakeModelClient):
    def extract_findings(self, analysis: str):
        self._record("extract_findings", {"analysis": analysis})
        raise RuntimeError("extract failed")


class FailingDeepDiveModel(FakeModelClient):
    def deep_dive(self, context):
        self._record(
            "deep_dive",
            {
                "company": context.company,
                "topic": context.topic,
            },
        )
        if context.topic == "Margin durability":
            raise RuntimeError("deep dive failed")
        return super().deep_dive(context)


class FailingDeepDiveWithRawResponseModel(FakeModelClient):
    def __init__(self):
        super().__init__()
        self._last_response_metadata = None
        self._last_response_text = None

    def deep_dive(self, context):
        self._record(
            "deep_dive",
            {
                "company": context.company,
                "topic": context.topic,
            },
        )
        self._last_response_metadata = {
            "done_reason": "stop",
            "eval_count": 219,
        }
        self._last_response_text = (
            '{"analysis":"The answer trails off supported by ",'
            '"abstract":"Partial.",'
            '"contradictions":[],'
            '"discovered_threads":[]}'
        )
        raise RuntimeError("deep-dive validation failed")

    def pop_last_response_metadata(self):
        metadata = self._last_response_metadata
        self._last_response_metadata = None
        return metadata

    def pop_last_response_text(self):
        response_text = self._last_response_text
        self._last_response_text = None
        return response_text


class FirstExistingThreadDedupModel(FakeModelClient):
    def deduplicate_investigation(self, context):
        self._record(
            "deduplicate_investigation",
            {
                "company": context.company,
                "candidate_topic": context.candidate_topic,
                "candidate_brief": context.candidate_brief,
                "existing_thread_count": len(context.existing_threads),
            },
        )
        if not context.existing_threads:
            return DeduplicationDecisionOutput(
                decision=DedupDecision.DISTINCT,
                canonical_node_id=None,
                reasoning="No existing threads.",
            )
        return DeduplicationDecisionOutput(
            decision=DedupDecision.REFERENCE_EXISTING,
            canonical_node_id=context.existing_threads[0].node_id,
            reasoning="The candidate matches the first existing thread.",
        )


class RecordingProgress:
    def __init__(self) -> None:
        self.run_ids: list[str] = []

    def __call__(self, conn, run_id: str) -> None:
        self.run_ids.append(run_id)


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

    def test_start_run_respects_max_total_nodes_for_scope_roots(self):
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

        run = start_run(
            self.conn,
            company="Example Co",
            model=model,
            config=WorkerConfig(max_total_nodes=1),
        )

        roots = db.root_nodes(self.conn, run.run_id)
        self.assertEqual(["Revenue quality"], [node.topic for node in roots])

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

    def test_duplicate_root_node_becomes_reference_without_running(self):
        scope = ScopeOutput.model_validate(
            {
                "root_threads": [
                    {
                        "topic": "Revenue quality",
                        "description": "Assess revenue quality.",
                        "priority": 1,
                        "investigation_brief": "Investigate revenue quality in filings.",
                    },
                    {
                        "topic": "Revenue quality",
                        "description": "Assess revenue quality again.",
                        "priority": 2,
                        "investigation_brief": "Investigate revenue quality in filings.",
                    },
                ]
            }
        )
        model = FirstExistingThreadDedupModel(
            scope_outputs=[scope],
        )
        run = start_run(self.conn, company="Example Co", model=model)
        run_to_completion(self.conn, run_id=run.run_id, model=model)

        roots = db.root_nodes(self.conn, run.run_id)
        self.assertEqual(2, len(roots))
        reference = db.node_reference(self.conn, roots[1].node_id)
        self.assertIsNotNone(reference)
        self.assertEqual(roots[0].node_id, reference["canonical_node_id"])
        self.assertEqual(
            {
                "scope": 1,
                "deduplicate_investigation": 1,
                "deep_dive": 1,
                "extract_findings": 1,
                "reflect": 1,
            },
            model.call_counts(),
        )

    def test_reference_child_waits_for_canonical_and_synthesizes_upward(self):
        reflect_root = ReflectOutput.model_validate(
            {
                "child_threads": [
                    thread_candidate(
                        topic="North Hoyle decommissioning",
                        priority=1,
                    ),
                    thread_candidate(
                        topic="North Hoyle decommissioning",
                        priority=2,
                    ),
                ]
            }
        )
        reflect_leaf = ReflectOutput.model_validate({"child_threads": []})
        model = FirstExistingThreadDedupModel(
            reflect_outputs=[reflect_root, reflect_leaf],
        )
        run = start_run(self.conn, company="Example Co", model=model)
        run_to_completion(self.conn, run_id=run.run_id, model=model)

        roots = db.root_nodes(self.conn, run.run_id)
        root = roots[0]
        children = db.child_nodes(self.conn, root.node_id)
        call = [
            c for c in db.model_calls(self.conn, run_id=run.run_id)
            if c.call_type == "deduplicate_investigation"
        ][0]
        payload = json.loads(call.input_json)
        first_child_id = payload["existing_threads"][0]["node_id"]
        self.assertEqual(1, len(payload["existing_threads"]))
        self.assertEqual(2, len(children))

        reference = db.node_reference(self.conn, children[1].node_id)
        self.assertIsNotNone(reference)
        self.assertEqual(first_child_id, reference["canonical_node_id"])
        self.assertEqual(
            NodeState.COMPLETE,
            db.get_node(self.conn, children[1].node_id).status,
        )

        branch_calls = [
            call for call in model.calls if call.call_type == "branch_synthesize"
        ]
        self.assertEqual(1, len(branch_calls))
        self.assertEqual(2, branch_calls[0].payload["child_summary_count"])
        self.assertEqual(
            {
                "scope": 1,
                "consolidate_siblings": 1,
                "deduplicate_investigation": 1,
                "deep_dive": 2,
                "extract_findings": 2,
                "reflect": 2,
                "branch_synthesize": 1,
            },
            model.call_counts(),
        )

    def test_reflected_siblings_are_consolidated_before_spawning(self):
        reflect_root = ReflectOutput.model_validate(
            {
                "child_threads": [
                    thread_candidate(topic="Merchant capture prices", priority=1),
                    thread_candidate(topic="Cannibalization impact", priority=1),
                    thread_candidate(topic="Negative pricing impact", priority=2),
                ]
            }
        )
        consolidate = SiblingConsolidationOutput.model_validate(
            {
                "child_threads": [
                    {
                        "topic": "Merchant capture prices and cannibalization",
                        "description": "Consolidated merchant price exposure thread.",
                        "material": True,
                        "priority": 1,
                        "resolution_state": "unresolved_investigable",
                        "evidence_basis": "direct",
                        "investigation_brief": "Investigate merchant capture prices, negative pricing, and cannibalization in one thread.",
                    }
                ],
                "reasoning": "The three siblings share one evidence hunt.",
            }
        )
        reflect_leaf = ReflectOutput.model_validate({"child_threads": []})
        model = FakeModelClient(
            reflect_outputs=[reflect_root, reflect_leaf],
            consolidate_sibling_outputs=[consolidate],
        )

        run = start_run(self.conn, company="Example Co", model=model)
        run_to_completion(self.conn, run_id=run.run_id, model=model)

        root = db.root_nodes(self.conn, run.run_id)[0]
        children = db.child_nodes(self.conn, root.node_id)
        self.assertEqual(1, len(children))
        self.assertEqual(
            "Merchant capture prices and cannibalization",
            children[0].topic,
        )
        self.assertEqual(
            {
                "scope": 1,
                "deep_dive": 2,
                "extract_findings": 2,
                "reflect": 2,
                "consolidate_siblings": 1,
                "branch_synthesize": 1,
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

    def test_worker_config_controls_search_result_count(self):
        model = FakeModelClient()
        search_provider = FakeSearchProvider([
            SourceMaterial(
                title=f"Source {index}",
                url=None,
                source_type="test",
                published_at=None,
                text=f"Text {index}.",
            )
            for index in range(3)
        ])

        run = start_run(self.conn, company="Example Co", model=model)
        run_to_completion(
            self.conn,
            run_id=run.run_id,
            model=model,
            search_provider=search_provider,
            config=WorkerConfig(search_results_per_node=2),
        )

        self.assertEqual(2, search_provider.calls[0]["max_results"])
        deep_dive_call = [
            call for call in model.calls if call.call_type == "deep_dive"
        ][0]
        self.assertEqual(2, deep_dive_call.payload["source_material_count"])

    def test_worker_uses_planned_search_queries(self):
        search_plan = SearchPlanOutput.model_validate(
            {
                "queries": [
                    {
                        "query": "Example Co annual report revenue",
                        "purpose": "Find filing evidence.",
                        "source_preference": "filings",
                    },
                    {
                        "query": "Example Co customer concentration",
                        "purpose": "Find customer concentration evidence.",
                        "source_preference": "official",
                    },
                ]
            }
        )
        model = FakeModelClient(search_plan_outputs=[search_plan])
        search_provider = FakeSearchProvider([
            SourceMaterial(
                title="Search result",
                url="https://example.com/result",
                source_type="test",
                published_at=None,
                text="Search result text.",
            )
        ])

        run = start_run(self.conn, company="Example Co", model=model)
        run_to_completion(
            self.conn,
            run_id=run.run_id,
            model=model,
            search_provider=search_provider,
            config=WorkerConfig(search_results_per_node=2, search_queries_per_node=2),
        )

        self.assertEqual(
            ["Example Co annual report revenue", "Example Co customer concentration"],
            [call["query"] for call in search_provider.calls],
        )
        self.assertEqual(
            "search_plan",
            [call.call_type for call in model.calls if call.call_type == "search_plan"][0],
        )

    def test_worker_spreads_result_budget_across_planned_queries(self):
        search_plan = SearchPlanOutput.model_validate(
            {
                "queries": [
                    {
                        "query": f"Example Co narrow query {index}",
                        "purpose": "Find one evidence type.",
                        "source_preference": "any",
                    }
                    for index in range(4)
                ]
            }
        )
        model = FakeModelClient(search_plan_outputs=[search_plan])

        class QuerySensitiveSearchProvider(FakeSearchProvider):
            def search(self, *, company: str, query: str, max_results: int = 5):
                self.calls.append(
                    {
                        "company": company,
                        "query": query,
                        "max_results": max_results,
                    }
                )
                return [
                    SourceMaterial(
                        title=f"Search result for {query}",
                        url=f"https://example.com/{query.replace(' ', '-')}",
                        source_type="test",
                        published_at=None,
                        text=f"Search result text for {query}.",
                    )
                ][:max_results]

        search_provider = QuerySensitiveSearchProvider()

        run = start_run(self.conn, company="Example Co", model=model)
        run_to_completion(
            self.conn,
            run_id=run.run_id,
            model=model,
            search_provider=search_provider,
            config=WorkerConfig(search_results_per_node=3, search_queries_per_node=4),
        )

        self.assertEqual(
            [
                "Example Co narrow query 0",
                "Example Co narrow query 1",
                "Example Co narrow query 2",
            ],
            [call["query"] for call in search_provider.calls],
        )
        self.assertEqual(
            [1, 1, 1],
            [call["max_results"] for call in search_provider.calls],
        )

    def test_worker_falls_back_when_search_plan_fails(self):
        class FailingSearchPlanModel(FakeModelClient):
            def search_plan(self, *, company, topic, investigation_brief):
                raise RuntimeError("search plan failed")

        model = FailingSearchPlanModel()
        search_provider = FakeSearchProvider([
            SourceMaterial(
                title="Fallback result",
                url="https://example.com/fallback",
                source_type="test",
                published_at=None,
                text="Fallback result text.",
            )
        ])

        run = start_run(self.conn, company="Example Co", model=model)
        completed = run_to_completion(
            self.conn,
            run_id=run.run_id,
            model=model,
            search_provider=search_provider,
        )

        self.assertEqual("complete", completed.status)
        self.assertEqual(1, len(search_provider.calls))
        self.assertIn("Example Co", search_provider.calls[0]["query"])
        search_plan_calls = [
            call for call in db.model_calls(self.conn, run_id=run.run_id)
            if call.call_type == "search_plan"
        ]
        self.assertEqual("search plan failed", search_plan_calls[0].error)

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
                "core_question": "Root analysis.",
                "source_assessment": "Root source assessment.",
                "key_findings": ["Root finding."],
                "evidence_gaps": [],
                "conclusion": "Root conclusion.",
                "abstract": "Root abstract.",
                "discovered_threads": [
                    thread_candidate(topic="Discovered sibling")
                ],
            }
        )
        second_deep_dive = DeepDiveOutput.model_validate(
            {
                "core_question": "Sibling analysis.",
                "source_assessment": "Sibling source assessment.",
                "key_findings": ["Sibling finding."],
                "evidence_gaps": [],
                "conclusion": "Sibling conclusion.",
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
        self.assertIn("core_question", json.loads(calls[1].output_json))
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

    def test_failed_structured_call_persists_raw_response_text(self):
        model = FailingDeepDiveWithRawResponseModel()

        run = start_run(self.conn, company="Example Co", model=model)
        run_to_completion(self.conn, run_id=run.run_id, model=model)

        calls = db.model_calls(self.conn, run_id=run.run_id)
        deep_dive_call = [
            call for call in calls if call.call_type == "deep_dive"
        ][0]
        output_payload = json.loads(deep_dive_call.output_json)

        self.assertEqual("deep-dive validation failed", deep_dive_call.error)
        self.assertIn("trails off supported by", deep_dive_call.output_text)
        self.assertEqual(
            {"done_reason": "stop", "eval_count": 219},
            output_payload["_model_response_metadata"],
        )

    def test_failed_child_does_not_block_sibling_completion_or_run_completion(self):
        root_reflect = ReflectOutput.model_validate(
            {
                "child_threads": [
                    thread_candidate(topic="Margin durability"),
                    thread_candidate(topic="Customer concentration"),
                ]
            }
        )
        leaf_reflect = ReflectOutput.model_validate({"child_threads": []})
        model = FailingDeepDiveModel(
            reflect_outputs=[root_reflect, leaf_reflect],
            branch_syntheses=["Root synthesis."],
        )

        run = start_run(self.conn, company="Example Co", model=model)
        completed = run_to_completion(self.conn, run_id=run.run_id, model=model)

        root = db.root_nodes(self.conn, run.run_id)[0]
        children = db.child_nodes(self.conn, root.node_id)
        failed_child = next(child for child in children if child.topic == "Margin durability")
        complete_child = next(
            child for child in children if child.topic == "Customer concentration"
        )

        self.assertEqual("complete", completed.status)
        self.assertEqual(NodeState.COMPLETE, root.status)
        self.assertEqual(NodeState.FAILED, failed_child.status)
        self.assertEqual(NodeState.COMPLETE, complete_child.status)
        self.assertEqual("Root synthesis.", root.branch_synthesis)
        self.assertEqual(
            ["deep dive failed"],
            [failure.error for failure in db.node_failures(self.conn, failed_child.node_id)],
        )

    def test_run_to_completion_recovers_transitional_nodes_before_processing(self):
        model = FakeModelClient()

        run = start_run(self.conn, company="Example Co", model=model)
        root = db.root_nodes(self.conn, run.run_id)[0]
        db.apply_node_event(
            self.conn,
            node_id=root.node_id,
            event=NodeEvent.START_INVESTIGATION,
        )

        completed = run_to_completion(self.conn, run_id=run.run_id, model=model)

        self.assertEqual("complete", completed.status)
        self.assertEqual(
            NodeState.COMPLETE,
            db.root_nodes(self.conn, run.run_id)[0].status,
        )

    def test_progress_callback_is_invoked_during_run(self):
        progress = RecordingProgress()
        model = FakeModelClient()

        run = start_run(
            self.conn,
            company="Example Co",
            model=model,
            progress_callback=progress,
        )
        run_to_completion(
            self.conn,
            run_id=run.run_id,
            model=model,
            progress_callback=progress,
        )

        self.assertGreaterEqual(len(progress.run_ids), 3)
        self.assertTrue(all(run_id == run.run_id for run_id in progress.run_ids))

    def test_wall_clock_budget_leaves_run_resumable_when_time_expires(self):
        model = FakeModelClient()

        run = start_run(self.conn, company="Example Co", model=model)
        paused = run_to_completion(
            self.conn,
            run_id=run.run_id,
            model=model,
            config=WorkerConfig(max_wall_clock_seconds=0),
        )

        self.assertEqual("running", paused.status)
        self.assertEqual(
            NodeState.PENDING,
            db.root_nodes(self.conn, run.run_id)[0].status,
        )


if __name__ == "__main__":
    unittest.main()
