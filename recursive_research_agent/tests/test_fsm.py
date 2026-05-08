import unittest

from app.fsm import (
    InvalidTransition,
    NodeEvent,
    NodeState,
    can_transition,
    is_terminal,
    transition_for,
    valid_events,
)


class NodeFsmTests(unittest.TestCase):
    def test_leaf_lifecycle_reaches_complete(self):
        state = NodeState.PENDING

        state = transition_for(state, NodeEvent.START_INVESTIGATION)
        self.assertEqual(NodeState.INVESTIGATING, state)

        state = transition_for(state, NodeEvent.DEEP_DIVE_SUCCEEDED)
        self.assertEqual(NodeState.REFLECTING, state)

        state = transition_for(state, NodeEvent.REFLECT_FOUND_NO_CHILDREN)
        self.assertEqual(NodeState.COMPLETE, state)

    def test_internal_node_lifecycle_reaches_complete(self):
        state = NodeState.PENDING

        state = transition_for(state, NodeEvent.START_INVESTIGATION)
        state = transition_for(state, NodeEvent.DEEP_DIVE_SUCCEEDED)
        state = transition_for(state, NodeEvent.REFLECT_FOUND_CHILDREN)
        self.assertEqual(NodeState.AWAITING_CHILDREN, state)

        state = transition_for(state, NodeEvent.CHILDREN_COMPLETED)
        self.assertEqual(NodeState.SYNTHESIZING, state)

        state = transition_for(state, NodeEvent.SYNTHESIS_SUCCEEDED)
        self.assertEqual(NodeState.COMPLETE, state)

    def test_reference_node_short_circuits_to_complete(self):
        state = transition_for(NodeState.PENDING, NodeEvent.MARK_REFERENCE)
        self.assertEqual(NodeState.REFERENCE, state)

        state = transition_for(state, NodeEvent.REFERENCE_COMPLETED)
        self.assertEqual(NodeState.COMPLETE, state)

    def test_circular_rejection_is_terminal(self):
        state = transition_for(NodeState.PENDING, NodeEvent.REJECT_CIRCULAR)

        self.assertEqual(NodeState.REJECTED, state)
        self.assertTrue(is_terminal(state))
        self.assertEqual((), valid_events(state))

    def test_active_states_can_fail(self):
        active_states = (
            NodeState.PENDING,
            NodeState.INVESTIGATING,
            NodeState.REFLECTING,
            NodeState.AWAITING_CHILDREN,
            NodeState.SYNTHESIZING,
        )

        for state in active_states:
            with self.subTest(state=state):
                self.assertEqual(
                    NodeState.FAILED,
                    transition_for(state, NodeEvent.NODE_FAILED),
                )

    def test_terminal_states_have_no_outgoing_transitions(self):
        for state in (
            NodeState.COMPLETE,
            NodeState.FAILED,
            NodeState.REJECTED,
        ):
            with self.subTest(state=state):
                self.assertTrue(is_terminal(state))
                self.assertEqual((), valid_events(state))

    def test_invalid_transition_raises(self):
        with self.assertRaises(InvalidTransition):
            transition_for(NodeState.PENDING, NodeEvent.DEEP_DIVE_SUCCEEDED)

    def test_can_transition_reports_validity_without_raising(self):
        self.assertTrue(
            can_transition(NodeState.PENDING, NodeEvent.START_INVESTIGATION)
        )
        self.assertFalse(
            can_transition(NodeState.PENDING, NodeEvent.SYNTHESIS_SUCCEEDED)
        )

    def test_valid_events_for_pending(self):
        self.assertEqual(
            (
                NodeEvent.START_INVESTIGATION,
                NodeEvent.MARK_REFERENCE,
                NodeEvent.REJECT_CIRCULAR,
                NodeEvent.NODE_FAILED,
            ),
            valid_events(NodeState.PENDING),
        )


if __name__ == "__main__":
    unittest.main()

