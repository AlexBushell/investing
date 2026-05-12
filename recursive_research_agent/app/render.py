"""Markdown renderers for run observability artifacts."""

from __future__ import annotations

import html
import re
import sqlite3
from pathlib import Path

from app import db
from app.fsm import NodeState


def render_audit_markdown(conn: sqlite3.Connection, run_id: str) -> str:
    """Render the compact brief-tree audit view for a run."""

    run = db.get_run(conn, run_id)
    lines = [
        f"# Brief Tree Audit: {run.company}",
        "",
        f"- Run ID: `{run.run_id}`",
        f"- Status: `{run.status}`",
        "",
        "## Nodes",
        "",
    ]

    roots = db.root_nodes(conn, run_id)
    if not roots:
        lines.append("_No nodes yet._")
    else:
        for node in roots:
            _render_audit_node(conn, node, lines)

    return _finish(lines)


def render_dossier_markdown(conn: sqlite3.Connection, run_id: str) -> str:
    """Render the full dossier markdown for a run."""

    run = db.get_run(conn, run_id)
    lines = [
        f"# Recursive Research Dossier: {run.company}",
        "",
        f"- Run ID: `{run.run_id}`",
        f"- Status: `{run.status}`",
        "",
    ]

    roots = db.root_nodes(conn, run_id)
    if not roots:
        lines.append("_No investigations completed._")
    else:
        for node in roots:
            _render_dossier_node(conn, node, lines)

    return _finish(lines)


def write_audit_markdown(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    output_path: str | Path,
) -> Path:
    """Render and write the audit markdown file."""

    return _write_text(output_path, render_audit_markdown(conn, run_id))


def write_dossier_markdown(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    output_path: str | Path,
) -> Path:
    """Render and write the dossier markdown file."""

    return _write_text(output_path, render_dossier_markdown(conn, run_id))


def _render_audit_node(
    conn: sqlite3.Connection,
    node: db.NodeDetail,
    lines: list[str],
) -> None:
    indent = "  " * node.depth
    lines.append(f"{indent}- **{node.topic}** [`{node.status.value}`]")
    lines.append(f"{indent}  - Node ID: `{node.node_id}`")
    lines.append(f"{indent}  - Priority: `{node.priority}`")
    lines.append(f"{indent}  - Material: `{str(node.material).lower()}`")
    lines.append(f"{indent}  - Resolution: `{node.resolution_state}`")
    lines.append(f"{indent}  - Evidence basis: `{node.evidence_basis}`")

    reference = db.node_reference(conn, node.node_id)
    if reference is not None:
        lines.append(f"{indent}  - Reference to: `{reference['canonical_node_id']}`")

    if node.status == NodeState.REJECTED:
        rejection = db.node_rejection(conn, node.node_id)
        if rejection is not None:
            lines.append(
                f"{indent}  - Rejection reason: "
                f"{_safe_markdown_text(rejection['reason'])}"
            )
            if rejection["duplicated_ancestor_id"]:
                lines.append(
                    f"{indent}  - Duplicated ancestor: "
                    f"`{rejection['duplicated_ancestor_id']}`"
                )

    if node.status == NodeState.FAILED:
        failures = db.node_failures(conn, node.node_id)
        if failures:
            latest = failures[-1]
            lines.append(f"{indent}  - Latest failure attempt: `{latest.attempt}`")
            lines.append(
                f"{indent}  - Latest failure: {_safe_markdown_text(latest.error)}"
            )

    if node.triggering_text_span:
        lines.append(
            f"{indent}  - Triggering span: "
            f"{_safe_markdown_text(node.triggering_text_span)}"
        )
    if node.why_unresolved:
        lines.append(
            f"{indent}  - Why unresolved: {_safe_markdown_text(node.why_unresolved)}"
        )

    lines.append(f"{indent}  - Brief:")
    lines.append("")
    lines.extend(
        _indented_block(_safe_markdown_text(node.investigation_brief), f"{indent}    ")
    )
    lines.append("")

    for child in db.child_nodes(conn, node.node_id):
        _render_audit_node(conn, child, lines)


def _render_dossier_node(
    conn: sqlite3.Connection,
    node: db.NodeDetail,
    lines: list[str],
) -> None:
    if node.status == NodeState.REJECTED:
        return

    heading_level = min(node.depth + 2, 6)
    lines.append(f"{'#' * heading_level} {node.topic}")
    lines.append("")

    reference = db.node_reference(conn, node.node_id)
    if reference is not None:
        lines.append(
            f"Reference node. See canonical node `{reference['canonical_node_id']}`."
        )
        lines.append("")
        return

    origins = db.canonical_reference_origins(conn, node.node_id)
    if origins:
        lines.append(
            "This concern was independently surfaced by "
            f"{len(origins)} investigations:"
        )
        lines.append("")
        for origin in origins:
            lines.append(f"- {_safe_markdown_text(origin)}")
        lines.append("")

    if node.branch_synthesis:
        lines.append(_safe_markdown_text(node.branch_synthesis))
        lines.append("")

    if node.analysis:
        lines.append(_safe_markdown_text(_reader_analysis(node.analysis)))
        lines.append("")
    elif node.status == NodeState.FAILED:
        lines.append(f"[investigation failed: {node.topic}]")
        failures = db.node_failures(conn, node.node_id)
        if failures:
            latest = failures[-1]
            lines.append("")
            lines.append(f"Latest failure attempt: `{latest.attempt}`")
            lines.append("")
            lines.append(f"Latest failure: {_safe_markdown_text(latest.error)}")
        lines.append("")
    else:
        lines.append(f"_[{node.status.value}: analysis not available yet]_")
        lines.append("")

    for child in db.child_nodes(conn, node.node_id):
        _render_dossier_node(conn, child, lines)


def _indented_block(text: str, prefix: str) -> list[str]:
    return [f"{prefix}{line}" if line else prefix.rstrip() for line in text.splitlines()]


def _reader_analysis(analysis: str) -> str:
    return analysis.rstrip().removesuffix("END_OF_DEEP_DIVE_ANALYSIS.").rstrip()


def _safe_markdown_text(text: str) -> str:
    sanitized = text.replace("\r\n", "\n").replace("\r", "\n")
    sanitized = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", sanitized)
    sanitized = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r"image: \1 (\2)", sanitized)
    sanitized = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", sanitized)
    sanitized = html.escape(sanitized, quote=False)
    return sanitized


def _write_text(output_path: str | Path, text: str) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _finish(lines: list[str]) -> str:
    return "\n".join(lines).rstrip() + "\n"
