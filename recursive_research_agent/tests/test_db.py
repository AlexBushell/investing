import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.db import (
    apply_node_event,
    connect,
    complete_model_call,
    create_model_call,
    create_node,
    create_run,
    initialize_database,
    node_failures,
    next_pending_node,
    record_node_failure,
    recover_transitional_nodes,
    node_events,
    model_calls,
)
from app.fsm import InvalidTransition, NodeEvent, NodeState


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "research.sqlite"
        self.conn = connect(self.db_path)
        initialize_database(self.conn)

    def tearDown(self):
        self.conn.close()
        self.temp_dir.cleanup()

    def test_initialize_database_records_schema_version(self):
        row = self.conn.execute(
            "SELECT version FROM schema_migrations"
        ).fetchone()

        self.assertEqual(1, row["version"])

    def test_create_run_and_node(self):
        run = create_run(self.conn, "Example Co")
        node = create_node(
            self.conn,
            run_id=run.run_id,
            topic="Revenue quality",
            investigation_brief="Investigate Example Co revenue quality.",
        )

        self.assertEqual("Example Co", run.company)
        self.assertEqual(NodeState.PENDING, node.status)
        self.assertEqual(0, node.depth)

    def test_child_node_depth_is_parent_depth_plus_one(self):
        run = create_run(self.conn, "Example Co")
        parent = create_node(
            self.conn,
            run_id=run.run_id,
            topic="Parent",
            investigation_brief="Parent brief.",
        )
        child = create_node(
            self.conn,
            run_id=run.run_id,
            parent_id=parent.node_id,
            topic="Child",
            investigation_brief="Child brief.",
        )

        self.assertEqual(1, child.depth)

    def test_next_pending_node_uses_priority_then_creation_order(self):
        run = create_run(self.conn, "Example Co")
        low = create_node(
            self.conn,
            run_id=run.run_id,
            topic="Low",
            investigation_brief="Low priority brief.",
            priority=3,
        )
        high = create_node(
            self.conn,
            run_id=run.run_id,
            topic="High",
            investigation_brief="High priority brief.",
            priority=1,
        )

        next_node = next_pending_node(self.conn, run_id=run.run_id)

        self.assertEqual(high.node_id, next_node.node_id)
        self.assertNotEqual(low.node_id, next_node.node_id)

    def test_apply_node_event_updates_status_and_logs_event(self):
        run = create_run(self.conn, "Example Co")
        node = create_node(
            self.conn,
            run_id=run.run_id,
            topic="Revenue quality",
            investigation_brief="Investigate Example Co revenue quality.",
        )

        updated = apply_node_event(
            self.conn,
            node_id=node.node_id,
            event=NodeEvent.START_INVESTIGATION,
            payload={"reason": "selected_from_frontier"},
        )

        self.assertEqual(NodeState.INVESTIGATING, updated.status)

        events = node_events(self.conn, node.node_id)
        self.assertEqual(1, len(events))
        self.assertEqual(NodeState.PENDING.value, events[0]["from_state"])
        self.assertEqual(NodeEvent.START_INVESTIGATION.value, events[0]["event"])
        self.assertEqual(NodeState.INVESTIGATING.value, events[0]["to_state"])
        self.assertEqual(
            {"reason": "selected_from_frontier"},
            json.loads(events[0]["payload_json"]),
        )

    def test_invalid_event_does_not_update_status_or_log_event(self):
        run = create_run(self.conn, "Example Co")
        node = create_node(
            self.conn,
            run_id=run.run_id,
            topic="Revenue quality",
            investigation_brief="Investigate Example Co revenue quality.",
        )

        with self.assertRaises(InvalidTransition):
            apply_node_event(
                self.conn,
                node_id=node.node_id,
                event=NodeEvent.DEEP_DIVE_SUCCEEDED,
            )

        row = self.conn.execute(
            "SELECT status FROM nodes WHERE node_id = ?",
            (node.node_id,),
        ).fetchone()
        self.assertEqual(NodeState.PENDING.value, row["status"])
        self.assertEqual([], node_events(self.conn, node.node_id))

    def test_foreign_keys_are_enforced(self):
        with self.assertRaises(sqlite3.IntegrityError):
            create_node(
                self.conn,
                run_id="missing-run",
                topic="Orphan",
                investigation_brief="Should fail.",
            )

    def test_model_call_records_input_output_and_error(self):
        run = create_run(self.conn, "Example Co")

        successful_call_id = create_model_call(
            self.conn,
            run_id=run.run_id,
            node_id=None,
            call_type="scope",
            model_name="fake-model",
            prompt_version="fake-v1",
            input_payload={"company": "Example Co"},
        )
        complete_model_call(
            self.conn,
            call_id=successful_call_id,
            output_payload={"root_threads": []},
        )

        failed_call_id = create_model_call(
            self.conn,
            run_id=run.run_id,
            node_id=None,
            call_type="reflect",
            model_name="fake-model",
            prompt_version="fake-v1",
            input_payload={"analysis": "bad"},
        )
        complete_model_call(
            self.conn,
            call_id=failed_call_id,
            error="validation failed",
        )

        calls = model_calls(self.conn, run_id=run.run_id)

        self.assertEqual(["scope", "reflect"], [call.call_type for call in calls])
        self.assertEqual({"company": "Example Co"}, json.loads(calls[0].input_json))
        self.assertEqual({"root_threads": []}, json.loads(calls[0].output_json))
        self.assertIsNone(calls[0].error)
        self.assertEqual("validation failed", calls[1].error)
        self.assertIsNotNone(calls[1].completed_at)

    def test_record_node_failure_increments_attempts(self):
        run = create_run(self.conn, "Example Co")
        node = create_node(
            self.conn,
            run_id=run.run_id,
            topic="Revenue quality",
            investigation_brief="Investigate Example Co revenue quality.",
        )

        first = record_node_failure(self.conn, node_id=node.node_id, error="first")
        second = record_node_failure(self.conn, node_id=node.node_id, error="second")
        failures = node_failures(self.conn, node.node_id)

        self.assertEqual(1, first.attempt)
        self.assertEqual(2, second.attempt)
        self.assertEqual(["first", "second"], [failure.error for failure in failures])

    def test_recover_transitional_nodes_resets_interrupted_states(self):
        run = create_run(self.conn, "Example Co")
        investigating = create_node(
            self.conn,
            run_id=run.run_id,
            topic="Investigating",
            investigation_brief="Investigate current work.",
        )
        reflecting = create_node(
            self.conn,
            run_id=run.run_id,
            topic="Reflecting",
            investigation_brief="Reflect on analysis.",
        )
        synthesizing = create_node(
            self.conn,
            run_id=run.run_id,
            topic="Synthesizing",
            investigation_brief="Synthesize completed branch.",
        )

        apply_node_event(
            self.conn,
            node_id=investigating.node_id,
            event=NodeEvent.START_INVESTIGATION,
        )
        apply_node_event(
            self.conn,
            node_id=reflecting.node_id,
            event=NodeEvent.START_INVESTIGATION,
        )
        apply_node_event(
            self.conn,
            node_id=reflecting.node_id,
            event=NodeEvent.DEEP_DIVE_SUCCEEDED,
        )
        apply_node_event(
            self.conn,
            node_id=synthesizing.node_id,
            event=NodeEvent.START_INVESTIGATION,
        )
        apply_node_event(
            self.conn,
            node_id=synthesizing.node_id,
            event=NodeEvent.DEEP_DIVE_SUCCEEDED,
        )
        apply_node_event(
            self.conn,
            node_id=synthesizing.node_id,
            event=NodeEvent.REFLECT_FOUND_CHILDREN,
        )
        apply_node_event(
            self.conn,
            node_id=synthesizing.node_id,
            event=NodeEvent.CHILDREN_COMPLETED,
        )

        recovered = recover_transitional_nodes(self.conn, run_id=run.run_id)

        self.assertEqual(3, recovered)
        statuses = {
            row["node_id"]: row["status"]
            for row in self.conn.execute(
                """
                SELECT node_id, status
                FROM nodes
                WHERE node_id IN (?, ?, ?)
                """,
                (
                    investigating.node_id,
                    reflecting.node_id,
                    synthesizing.node_id,
                ),
            )
        }
        self.assertEqual(NodeState.PENDING.value, statuses[investigating.node_id])
        self.assertEqual(NodeState.PENDING.value, statuses[reflecting.node_id])
        self.assertEqual(
            NodeState.AWAITING_CHILDREN.value,
            statuses[synthesizing.node_id],
        )


if __name__ == "__main__":
    unittest.main()
