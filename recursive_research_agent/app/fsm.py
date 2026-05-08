"""Finite state machine for research node lifecycles.

The FSM is intentionally pure: it validates state/event pairs and returns the
next state. Side effects such as model calls, database writes, rendering, and
failure logging belong to the worker and persistence layers.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class InvalidTransition(ValueError):
    """Raised when a node event is not valid for the current node state."""


class NodeState(str, Enum):
    """Durable lifecycle states for a research node."""

    PENDING = "pending"
    INVESTIGATING = "investigating"
    REFLECTING = "reflecting"
    AWAITING_CHILDREN = "awaiting_children"
    SYNTHESIZING = "synthesizing"
    REFERENCE = "reference"
    REJECTED = "rejected"
    COMPLETE = "complete"
    FAILED = "failed"


class NodeEvent(str, Enum):
    """Events that move a node through its lifecycle."""

    START_INVESTIGATION = "start_investigation"
    MARK_REFERENCE = "mark_reference"
    REJECT_CIRCULAR = "reject_circular"
    DEEP_DIVE_SUCCEEDED = "deep_dive_succeeded"
    REFLECT_FOUND_CHILDREN = "reflect_found_children"
    REFLECT_FOUND_NO_CHILDREN = "reflect_found_no_children"
    CHILDREN_COMPLETED = "children_completed"
    SYNTHESIS_SUCCEEDED = "synthesis_succeeded"
    REFERENCE_COMPLETED = "reference_completed"
    NODE_FAILED = "node_failed"


@dataclass(frozen=True)
class Transition:
    """A valid transition from one state to another via an event."""

    source: NodeState
    event: NodeEvent
    target: NodeState


TRANSITIONS: tuple[Transition, ...] = (
    Transition(
        NodeState.PENDING,
        NodeEvent.START_INVESTIGATION,
        NodeState.INVESTIGATING,
    ),
    Transition(
        NodeState.PENDING,
        NodeEvent.MARK_REFERENCE,
        NodeState.REFERENCE,
    ),
    Transition(
        NodeState.PENDING,
        NodeEvent.REJECT_CIRCULAR,
        NodeState.REJECTED,
    ),
    Transition(
        NodeState.PENDING,
        NodeEvent.NODE_FAILED,
        NodeState.FAILED,
    ),
    Transition(
        NodeState.INVESTIGATING,
        NodeEvent.DEEP_DIVE_SUCCEEDED,
        NodeState.REFLECTING,
    ),
    Transition(
        NodeState.INVESTIGATING,
        NodeEvent.NODE_FAILED,
        NodeState.FAILED,
    ),
    Transition(
        NodeState.REFLECTING,
        NodeEvent.REFLECT_FOUND_CHILDREN,
        NodeState.AWAITING_CHILDREN,
    ),
    Transition(
        NodeState.REFLECTING,
        NodeEvent.REFLECT_FOUND_NO_CHILDREN,
        NodeState.COMPLETE,
    ),
    Transition(
        NodeState.REFLECTING,
        NodeEvent.NODE_FAILED,
        NodeState.FAILED,
    ),
    Transition(
        NodeState.AWAITING_CHILDREN,
        NodeEvent.CHILDREN_COMPLETED,
        NodeState.SYNTHESIZING,
    ),
    Transition(
        NodeState.AWAITING_CHILDREN,
        NodeEvent.NODE_FAILED,
        NodeState.FAILED,
    ),
    Transition(
        NodeState.SYNTHESIZING,
        NodeEvent.SYNTHESIS_SUCCEEDED,
        NodeState.COMPLETE,
    ),
    Transition(
        NodeState.SYNTHESIZING,
        NodeEvent.NODE_FAILED,
        NodeState.FAILED,
    ),
    Transition(
        NodeState.REFERENCE,
        NodeEvent.REFERENCE_COMPLETED,
        NodeState.COMPLETE,
    ),
)

TRANSITION_TABLE: dict[tuple[NodeState, NodeEvent], NodeState] = {
    (transition.source, transition.event): transition.target
    for transition in TRANSITIONS
}

TERMINAL_STATES: frozenset[NodeState] = frozenset(
    {
        NodeState.COMPLETE,
        NodeState.FAILED,
        NodeState.REJECTED,
    }
)


def transition_for(state: NodeState, event: NodeEvent) -> NodeState:
    """Return the next state for a state/event pair.

    Raises:
        InvalidTransition: if the event is not valid for the current state.
    """

    try:
        return TRANSITION_TABLE[(state, event)]
    except KeyError as exc:
        raise InvalidTransition(
            f"No transition from {state.value!r} via {event.value!r}."
        ) from exc


def can_transition(state: NodeState, event: NodeEvent) -> bool:
    """Return whether an event is valid for a state."""

    return (state, event) in TRANSITION_TABLE


def valid_events(state: NodeState) -> tuple[NodeEvent, ...]:
    """Return all events that are valid for a state."""

    return tuple(
        transition.event
        for transition in TRANSITIONS
        if transition.source == state
    )


def is_terminal(state: NodeState) -> bool:
    """Return whether a state has no outgoing transitions."""

    return state in TERMINAL_STATES

