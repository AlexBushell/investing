"""SQLite persistence for recursive research runs.

The database layer is deliberately small at this stage. It owns schema
creation, basic run/node records, and transactional FSM event application.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from app.fsm import NodeEvent, NodeState, transition_for


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    company: str
    status: str


@dataclass(frozen=True)
class NodeRecord:
    node_id: str
    run_id: str
    parent_id: str | None
    status: NodeState
    topic: str
    priority: int
    depth: int


@dataclass(frozen=True)
class NodeDetail:
    node_id: str
    run_id: str
    parent_id: str | None
    status: NodeState
    topic: str
    description: str
    material: bool
    priority: int
    resolution_state: str
    evidence_basis: str
    triggering_text_span: str | None
    why_unresolved: str | None
    investigation_brief: str
    analysis: str | None
    abstract: str | None
    branch_synthesis: str | None
    depth: int


@dataclass(frozen=True)
class ModelCallDetail:
    call_id: str
    run_id: str
    node_id: str | None
    call_type: str
    model_name: str
    prompt_version: str
    input_json: str
    output_json: str | None
    output_text: str | None
    error: str | None
    started_at: str
    completed_at: str | None


def utc_now() -> str:
    """Return the current UTC time as an ISO-8601 string."""

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection configured for this application."""

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a block in a transaction, rolling back on error."""

    try:
        conn.execute("BEGIN")
        yield conn
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()


def initialize_database(conn: sqlite3.Connection) -> None:
    """Create the v1 database schema if it does not already exist."""

    with transaction(conn):
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                company TEXT NOT NULL,
                parent_run_id TEXT,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                status TEXT NOT NULL,
                FOREIGN KEY (parent_run_id) REFERENCES runs(run_id)
            );

            CREATE TABLE IF NOT EXISTS nodes (
                node_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                parent_id TEXT,
                canonical_node_id TEXT,
                reference_count INTEGER NOT NULL DEFAULT 0,
                topic TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                material INTEGER NOT NULL DEFAULT 1,
                priority INTEGER NOT NULL DEFAULT 2,
                resolution_state TEXT NOT NULL DEFAULT 'unresolved_investigable',
                evidence_basis TEXT NOT NULL DEFAULT 'direct',
                triggering_text_span TEXT,
                why_unresolved TEXT,
                investigation_brief TEXT NOT NULL,
                analysis TEXT,
                abstract TEXT,
                branch_synthesis TEXT,
                status TEXT NOT NULL,
                depth INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(run_id),
                FOREIGN KEY (parent_id) REFERENCES nodes(node_id),
                FOREIGN KEY (canonical_node_id) REFERENCES nodes(node_id)
            );

            CREATE TABLE IF NOT EXISTS node_references (
                canonical_node_id TEXT NOT NULL,
                reference_node_id TEXT NOT NULL,
                origin_brief TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (canonical_node_id, reference_node_id),
                FOREIGN KEY (canonical_node_id) REFERENCES nodes(node_id),
                FOREIGN KEY (reference_node_id) REFERENCES nodes(node_id)
            );

            CREATE TABLE IF NOT EXISTS node_failures (
                failure_id TEXT PRIMARY KEY,
                node_id TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                error TEXT NOT NULL,
                failed_at TEXT NOT NULL,
                FOREIGN KEY (node_id) REFERENCES nodes(node_id)
            );

            CREATE TABLE IF NOT EXISTS node_rejections (
                rejection_id TEXT PRIMARY KEY,
                node_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                duplicated_ancestor_id TEXT,
                rejected_at TEXT NOT NULL,
                FOREIGN KEY (node_id) REFERENCES nodes(node_id),
                FOREIGN KEY (duplicated_ancestor_id) REFERENCES nodes(node_id)
            );

            CREATE TABLE IF NOT EXISTS node_events (
                event_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                node_id TEXT NOT NULL,
                from_state TEXT NOT NULL,
                event TEXT NOT NULL,
                to_state TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(run_id),
                FOREIGN KEY (node_id) REFERENCES nodes(node_id)
            );

            CREATE TABLE IF NOT EXISTS model_calls (
                call_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                node_id TEXT,
                call_type TEXT NOT NULL,
                model_name TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                input_json TEXT NOT NULL,
                output_json TEXT,
                output_text TEXT,
                error TEXT,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                FOREIGN KEY (run_id) REFERENCES runs(run_id),
                FOREIGN KEY (node_id) REFERENCES nodes(node_id)
            );

            CREATE INDEX IF NOT EXISTS idx_nodes_run_status_priority
            ON nodes(run_id, status, priority, created_at);

            CREATE INDEX IF NOT EXISTS idx_nodes_parent
            ON nodes(parent_id);

            CREATE INDEX IF NOT EXISTS idx_node_events_node
            ON node_events(node_id, created_at);
            """
        )

        conn.execute(
            """
            INSERT OR IGNORE INTO schema_migrations (version, applied_at)
            VALUES (?, ?)
            """,
            (SCHEMA_VERSION, utc_now()),
        )


def create_run(conn: sqlite3.Connection, company: str) -> RunRecord:
    """Create a new run record."""

    run_id = str(uuid4())
    now = utc_now()
    with transaction(conn):
        conn.execute(
            """
            INSERT INTO runs (
                run_id, company, parent_run_id, started_at, completed_at, status
            )
            VALUES (?, ?, NULL, ?, NULL, ?)
            """,
            (run_id, company, now, "running"),
        )

    return RunRecord(run_id=run_id, company=company, status="running")


def create_node(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    topic: str,
    investigation_brief: str,
    parent_id: str | None = None,
    description: str = "",
    material: bool = True,
    priority: int = 2,
    resolution_state: str = "unresolved_investigable",
    evidence_basis: str = "direct",
    triggering_text_span: str | None = None,
    why_unresolved: str | None = None,
) -> NodeRecord:
    """Create a pending node."""

    node_id = str(uuid4())
    depth = _depth_for_parent(conn, parent_id)
    now = utc_now()
    with transaction(conn):
        conn.execute(
            """
            INSERT INTO nodes (
                node_id, run_id, parent_id, topic, description, material,
                priority, resolution_state, evidence_basis, triggering_text_span,
                why_unresolved, investigation_brief, status, depth, created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                node_id,
                run_id,
                parent_id,
                topic,
                description,
                int(material),
                priority,
                resolution_state,
                evidence_basis,
                triggering_text_span,
                why_unresolved,
                investigation_brief,
                NodeState.PENDING.value,
                depth,
                now,
                now,
            ),
        )

    return NodeRecord(
        node_id=node_id,
        run_id=run_id,
        parent_id=parent_id,
        status=NodeState.PENDING,
        topic=topic,
        priority=priority,
        depth=depth,
    )


def get_node(conn: sqlite3.Connection, node_id: str) -> NodeRecord:
    """Fetch a node by id."""

    row = conn.execute(
        """
        SELECT node_id, run_id, parent_id, status, topic, priority, depth
        FROM nodes
        WHERE node_id = ?
        """,
        (node_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"Node not found: {node_id}")
    return _node_from_row(row)


def get_node_detail(conn: sqlite3.Connection, node_id: str) -> NodeDetail:
    """Fetch the full node fields needed by the worker."""

    row = conn.execute(
        """
        SELECT
            node_id, run_id, parent_id, status, topic, description, material,
            priority, resolution_state, evidence_basis, triggering_text_span,
            why_unresolved, investigation_brief, analysis, abstract,
            branch_synthesis, depth
        FROM nodes
        WHERE node_id = ?
        """,
        (node_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"Node not found: {node_id}")
    return _node_detail_from_row(row)


def get_run(conn: sqlite3.Connection, run_id: str) -> RunRecord:
    """Fetch a run by id."""

    row = conn.execute(
        """
        SELECT run_id, company, status
        FROM runs
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"Run not found: {run_id}")
    return RunRecord(
        run_id=row["run_id"],
        company=row["company"],
        status=row["status"],
    )


def apply_node_event(
    conn: sqlite3.Connection,
    *,
    node_id: str,
    event: NodeEvent,
    payload: dict[str, Any] | None = None,
) -> NodeRecord:
    """Apply an FSM event to a node and persist the transition atomically."""

    payload = payload or {}
    now = utc_now()

    with transaction(conn):
        current = get_node(conn, node_id)
        next_status = transition_for(current.status, event)

        conn.execute(
            """
            UPDATE nodes
            SET status = ?, updated_at = ?
            WHERE node_id = ?
            """,
            (next_status.value, now, node_id),
        )
        conn.execute(
            """
            INSERT INTO node_events (
                event_id, run_id, node_id, from_state, event, to_state,
                payload_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                current.run_id,
                node_id,
                current.status.value,
                event.value,
                next_status.value,
                json.dumps(payload, sort_keys=True),
                now,
            ),
        )

    return get_node(conn, node_id)


def store_deep_dive_output(
    conn: sqlite3.Connection,
    *,
    node_id: str,
    analysis: str,
    abstract: str,
) -> None:
    """Store a node's deep-dive analysis and abstract."""

    with transaction(conn):
        conn.execute(
            """
            UPDATE nodes
            SET analysis = ?, abstract = ?, updated_at = ?
            WHERE node_id = ?
            """,
            (analysis, abstract, utc_now(), node_id),
        )


def store_branch_synthesis(
    conn: sqlite3.Connection,
    *,
    node_id: str,
    branch_synthesis: str,
) -> None:
    """Store a node's branch synthesis."""

    with transaction(conn):
        conn.execute(
            """
            UPDATE nodes
            SET branch_synthesis = ?, updated_at = ?
            WHERE node_id = ?
            """,
            (branch_synthesis, utc_now(), node_id),
        )


def complete_run(conn: sqlite3.Connection, run_id: str) -> RunRecord:
    """Mark a run complete."""

    now = utc_now()
    with transaction(conn):
        conn.execute(
            """
            UPDATE runs
            SET status = ?, completed_at = ?
            WHERE run_id = ?
            """,
            ("complete", now, run_id),
        )
    return get_run(conn, run_id)


def next_pending_node(
    conn: sqlite3.Connection,
    *,
    run_id: str,
) -> NodeRecord | None:
    """Return the next pending node by priority and creation time."""

    row = conn.execute(
        """
        SELECT node_id, run_id, parent_id, status, topic, priority, depth
        FROM nodes
        WHERE run_id = ? AND status = ?
        ORDER BY priority ASC, created_at ASC
        LIMIT 1
        """,
        (run_id, NodeState.PENDING.value),
    ).fetchone()
    if row is None:
        return None
    return _node_from_row(row)


def first_pending_node(
    conn: sqlite3.Connection,
    *,
    run_id: str,
) -> NodeDetail | None:
    """Return the first pending node with full details."""

    node = next_pending_node(conn, run_id=run_id)
    if node is None:
        return None
    return get_node_detail(conn, node.node_id)


def next_synthesis_ready_node(
    conn: sqlite3.Connection,
    *,
    run_id: str,
) -> NodeRecord | None:
    """Return an awaiting node whose children have all reached terminal states."""

    row = conn.execute(
        """
        SELECT n.node_id, n.run_id, n.parent_id, n.status, n.topic, n.priority, n.depth
        FROM nodes n
        WHERE n.run_id = ?
          AND n.status = ?
          AND NOT EXISTS (
              SELECT 1
              FROM nodes c
              WHERE c.parent_id = n.node_id
                AND c.status NOT IN (?, ?, ?)
          )
        ORDER BY n.depth DESC, n.priority ASC, n.created_at ASC
        LIMIT 1
        """,
        (
            run_id,
            NodeState.AWAITING_CHILDREN.value,
            NodeState.COMPLETE.value,
            NodeState.FAILED.value,
            NodeState.REJECTED.value,
        ),
    ).fetchone()
    if row is None:
        return None
    return _node_from_row(row)


def child_nodes(conn: sqlite3.Connection, node_id: str) -> list[NodeDetail]:
    """Return a node's children in render/queue order."""

    return [
        _node_detail_from_row(row)
        for row in conn.execute(
            """
            SELECT
                node_id, run_id, parent_id, status, topic, description, material,
                priority, resolution_state, evidence_basis, triggering_text_span,
                why_unresolved, investigation_brief, analysis, abstract,
                branch_synthesis, depth
            FROM nodes
            WHERE parent_id = ?
            ORDER BY priority ASC, created_at ASC
            """,
            (node_id,),
        )
    ]


def root_nodes(conn: sqlite3.Connection, run_id: str) -> list[NodeDetail]:
    """Return root nodes for a run in render/queue order."""

    return [
        _node_detail_from_row(row)
        for row in conn.execute(
            """
            SELECT
                node_id, run_id, parent_id, status, topic, description, material,
                priority, resolution_state, evidence_basis, triggering_text_span,
                why_unresolved, investigation_brief, analysis, abstract,
                branch_synthesis, depth
            FROM nodes
            WHERE run_id = ? AND parent_id IS NULL
            ORDER BY priority ASC, created_at ASC
            """,
            (run_id,),
        )
    ]


def has_open_nodes(conn: sqlite3.Connection, run_id: str) -> bool:
    """Return whether a run has nodes that are not terminal."""

    row = conn.execute(
        """
        SELECT 1
        FROM nodes
        WHERE run_id = ?
          AND status NOT IN (?, ?, ?)
        LIMIT 1
        """,
        (
            run_id,
            NodeState.COMPLETE.value,
            NodeState.FAILED.value,
            NodeState.REJECTED.value,
        ),
    ).fetchone()
    return row is not None


def node_count(conn: sqlite3.Connection, run_id: str) -> int:
    """Return the number of nodes in a run."""

    row = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM nodes
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    return int(row["count"])


def node_events(conn: sqlite3.Connection, node_id: str) -> list[sqlite3.Row]:
    """Return the event log for a node."""

    return list(
        conn.execute(
            """
            SELECT from_state, event, to_state, payload_json, created_at
            FROM node_events
            WHERE node_id = ?
            ORDER BY created_at ASC
            """,
            (node_id,),
        )
    )


def create_model_call(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    node_id: str | None,
    call_type: str,
    model_name: str,
    prompt_version: str,
    input_payload: dict[str, Any],
) -> str:
    """Create a model call record and return its id."""

    call_id = str(uuid4())
    with transaction(conn):
        conn.execute(
            """
            INSERT INTO model_calls (
                call_id, run_id, node_id, call_type, model_name, prompt_version,
                input_json, output_json, output_text, error, started_at,
                completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, NULL)
            """,
            (
                call_id,
                run_id,
                node_id,
                call_type,
                model_name,
                prompt_version,
                json.dumps(input_payload, sort_keys=True),
                utc_now(),
            ),
        )
    return call_id


def complete_model_call(
    conn: sqlite3.Connection,
    *,
    call_id: str,
    output_payload: dict[str, Any] | None = None,
    output_text: str | None = None,
    error: str | None = None,
) -> None:
    """Complete a model call record with output or error details."""

    with transaction(conn):
        conn.execute(
            """
            UPDATE model_calls
            SET output_json = ?, output_text = ?, error = ?, completed_at = ?
            WHERE call_id = ?
            """,
            (
                (
                    json.dumps(output_payload, sort_keys=True)
                    if output_payload is not None
                    else None
                ),
                output_text,
                error,
                utc_now(),
                call_id,
            ),
        )


def model_calls(
    conn: sqlite3.Connection,
    *,
    run_id: str,
) -> list[ModelCallDetail]:
    """Return model call records for a run in creation order."""

    return [
        _model_call_from_row(row)
        for row in conn.execute(
            """
            SELECT
                call_id, run_id, node_id, call_type, model_name, prompt_version,
                input_json, output_json, output_text, error, started_at,
                completed_at
            FROM model_calls
            WHERE run_id = ?
            ORDER BY rowid ASC
            """,
            (run_id,),
        )
    ]


def node_rejection(conn: sqlite3.Connection, node_id: str) -> sqlite3.Row | None:
    """Return rejection metadata for a node if present."""

    return conn.execute(
        """
        SELECT reason, duplicated_ancestor_id, rejected_at
        FROM node_rejections
        WHERE node_id = ?
        ORDER BY rejected_at DESC
        LIMIT 1
        """,
        (node_id,),
    ).fetchone()


def node_reference(conn: sqlite3.Connection, node_id: str) -> sqlite3.Row | None:
    """Return reference metadata for a reference node if present."""

    return conn.execute(
        """
        SELECT canonical_node_id, reference_node_id, origin_brief, created_at
        FROM node_references
        WHERE reference_node_id = ?
        LIMIT 1
        """,
        (node_id,),
    ).fetchone()


def canonical_reference_origins(
    conn: sqlite3.Connection,
    canonical_node_id: str,
) -> list[str]:
    """Return origin briefs for references pointing at a canonical node."""

    return [
        row["origin_brief"]
        for row in conn.execute(
            """
            SELECT origin_brief
            FROM node_references
            WHERE canonical_node_id = ?
            ORDER BY created_at ASC
            """,
            (canonical_node_id,),
        )
    ]


def _depth_for_parent(conn: sqlite3.Connection, parent_id: str | None) -> int:
    if parent_id is None:
        return 0

    row = conn.execute(
        "SELECT depth FROM nodes WHERE node_id = ?",
        (parent_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"Parent node not found: {parent_id}")
    return int(row["depth"]) + 1


def _node_from_row(row: sqlite3.Row) -> NodeRecord:
    return NodeRecord(
        node_id=row["node_id"],
        run_id=row["run_id"],
        parent_id=row["parent_id"],
        status=NodeState(row["status"]),
        topic=row["topic"],
        priority=int(row["priority"]),
        depth=int(row["depth"]),
    )


def _node_detail_from_row(row: sqlite3.Row) -> NodeDetail:
    return NodeDetail(
        node_id=row["node_id"],
        run_id=row["run_id"],
        parent_id=row["parent_id"],
        status=NodeState(row["status"]),
        topic=row["topic"],
        description=row["description"],
        material=bool(row["material"]),
        priority=int(row["priority"]),
        resolution_state=row["resolution_state"],
        evidence_basis=row["evidence_basis"],
        triggering_text_span=row["triggering_text_span"],
        why_unresolved=row["why_unresolved"],
        investigation_brief=row["investigation_brief"],
        analysis=row["analysis"],
        abstract=row["abstract"],
        branch_synthesis=row["branch_synthesis"],
        depth=int(row["depth"]),
    )


def _model_call_from_row(row: sqlite3.Row) -> ModelCallDetail:
    return ModelCallDetail(
        call_id=row["call_id"],
        run_id=row["run_id"],
        node_id=row["node_id"],
        call_type=row["call_type"],
        model_name=row["model_name"],
        prompt_version=row["prompt_version"],
        input_json=row["input_json"],
        output_json=row["output_json"],
        output_text=row["output_text"],
        error=row["error"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
    )
