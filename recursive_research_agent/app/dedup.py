"""Within-run investigation deduplication helpers."""

from __future__ import annotations

import sqlite3

from app import db
from app.fsm import NodeState


def existing_thread_candidates(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    node_id: str,
) -> tuple[db.NodeDetail, ...]:
    """Return eligible same-run canonical threads for dedup arbitration."""

    candidate = db.get_node_detail(conn, node_id)
    ancestor_ids = _ancestor_ids(conn, candidate)
    all_nodes = db.run_nodes(conn, run_id)
    candidate_index = next(
        index for index, other in enumerate(all_nodes) if other.node_id == node_id
    )

    eligible: list[db.NodeDetail] = []
    for other in all_nodes[:candidate_index]:
        if other.node_id in ancestor_ids:
            continue
        if other.canonical_node_id is not None:
            continue
        if other.status in {NodeState.REJECTED, NodeState.FAILED}:
            continue
        eligible.append(other)
    return tuple(eligible)


def _ancestor_ids(conn: sqlite3.Connection, node: db.NodeDetail) -> set[str]:
    ancestor_ids: set[str] = set()
    parent_id = node.parent_id
    while parent_id is not None:
        ancestor_ids.add(parent_id)
        parent = db.get_node_detail(conn, parent_id)
        parent_id = parent.parent_id
    return ancestor_ids
