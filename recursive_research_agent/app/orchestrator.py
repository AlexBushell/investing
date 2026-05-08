"""Serial worker for the recursive research lifecycle.

This is the first vertical slice of orchestration. It intentionally excludes
deduplication, findings retrieval, rendering, and real search/model providers.
The goal is to prove that persisted nodes can move through the lifecycle using
the FSM and typed model boundary.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, TypeVar

from app import db
from app.fsm import NodeEvent, NodeState
from app.llm import (
    AncestorContext,
    BranchSynthesisContext,
    ChildSummary,
    DeepDiveContext,
    ResearchModelClient,
    SourceMaterialContext,
)
from app.schemas import ThreadCandidate
from app.search import SearchProvider


@dataclass(frozen=True)
class WorkerConfig:
    max_depth: int = 8
    max_total_nodes: int = 500
    model_name: str = "fake-model"
    prompt_version: str = "fake-v1"


T = TypeVar("T")


def start_run(
    conn: sqlite3.Connection,
    *,
    company: str,
    model: ResearchModelClient,
    config: WorkerConfig | None = None,
) -> db.RunRecord:
    """Create a run and seed root nodes from the scope call."""

    config = config or WorkerConfig()
    run = db.create_run(conn, company)
    scope = _record_structured_model_call(
        conn,
        run_id=run.run_id,
        node_id=None,
        call_type="scope",
        input_payload={"company": company},
        call=lambda: model.scope(company),
        config=config,
    )

    for brief in scope.root_threads:
        db.create_node(
            conn,
            run_id=run.run_id,
            topic=brief.topic,
            description=brief.description,
            priority=brief.priority,
            investigation_brief=brief.investigation_brief,
        )

    return run


def run_to_completion(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    model: ResearchModelClient,
    search_provider: SearchProvider | None = None,
    config: WorkerConfig | None = None,
) -> db.RunRecord:
    """Process a run until no work remains."""

    config = config or WorkerConfig()
    while process_next_action(
        conn,
        run_id=run_id,
        model=model,
        search_provider=search_provider,
        config=config,
    ):
        pass
    return db.get_run(conn, run_id)


def process_next_action(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    model: ResearchModelClient,
    search_provider: SearchProvider | None = None,
    config: WorkerConfig | None = None,
) -> bool:
    """Process one pending or synthesis-ready node.

    Returns true when work was performed. Returns false when the run has no
    remaining open nodes, after marking the run complete.
    """

    config = config or WorkerConfig()

    pending = db.next_pending_node(conn, run_id=run_id)
    if pending is not None:
        _process_pending_node(
            conn,
            node_id=pending.node_id,
            model=model,
            search_provider=search_provider,
            config=config,
        )
        return True

    synthesis_ready = db.next_synthesis_ready_node(conn, run_id=run_id)
    if synthesis_ready is not None:
        _process_synthesis_ready_node(
            conn,
            node_id=synthesis_ready.node_id,
            model=model,
            config=config,
        )
        return True

    if not db.has_open_nodes(conn, run_id):
        run = db.get_run(conn, run_id)
        if run.status != "complete":
            db.complete_run(conn, run_id)
        return False

    return False


def _process_pending_node(
    conn: sqlite3.Connection,
    *,
    node_id: str,
    model: ResearchModelClient,
    search_provider: SearchProvider | None,
    config: WorkerConfig,
) -> None:
    node = db.get_node_detail(conn, node_id)
    run = db.get_run(conn, node.run_id)

    db.apply_node_event(
        conn,
        node_id=node.node_id,
        event=NodeEvent.START_INVESTIGATION,
    )

    try:
        deep_dive_context = DeepDiveContext(
            company=run.company,
            topic=node.topic,
            investigation_brief=node.investigation_brief,
            ancestors=_ancestor_context(conn, node),
            source_materials=_source_material_contexts(
                search_provider,
                company=run.company,
                node=node,
            ),
        )
        deep_dive = _record_structured_model_call(
            conn,
            run_id=node.run_id,
            node_id=node.node_id,
            call_type="deep_dive",
            input_payload=_jsonable(deep_dive_context),
            call=lambda: model.deep_dive(deep_dive_context),
            config=config,
        )
        db.store_deep_dive_output(
            conn,
            node_id=node.node_id,
            analysis=deep_dive.analysis,
            abstract=deep_dive.abstract,
        )
        db.apply_node_event(
            conn,
            node_id=node.node_id,
            event=NodeEvent.DEEP_DIVE_SUCCEEDED,
        )

        try:
            _record_structured_model_call(
                conn,
                run_id=node.run_id,
                node_id=node.node_id,
                call_type="extract_findings",
                input_payload={"analysis": deep_dive.analysis},
                call=lambda: model.extract_findings(deep_dive.analysis),
                config=config,
            )
        except Exception:
            # Findings extraction is non-fatal by spec. Detailed failure logging
            # is already persisted in model_calls by the wrapper above.
            pass

        reflect = _record_structured_model_call(
            conn,
            run_id=node.run_id,
            node_id=node.node_id,
            call_type="reflect",
            input_payload={"analysis": deep_dive.analysis},
            call=lambda: model.reflect(deep_dive.analysis),
            config=config,
        )
        child_count = _spawn_child_threads(
            conn,
            run_id=node.run_id,
            parent_id=node.node_id,
            parent_depth=node.depth,
            candidates=reflect.child_threads,
            config=config,
        )
        _spawn_discovered_threads(
            conn,
            run_id=node.run_id,
            parent_id=node.parent_id,
            sibling_depth=node.depth,
            candidates=deep_dive.discovered_threads,
            config=config,
        )

        event = (
            NodeEvent.REFLECT_FOUND_CHILDREN
            if child_count > 0
            else NodeEvent.REFLECT_FOUND_NO_CHILDREN
        )
        db.apply_node_event(
            conn,
            node_id=node.node_id,
            event=event,
            payload={"child_count": child_count},
        )
    except Exception as exc:
        db.apply_node_event(
            conn,
            node_id=node.node_id,
            event=NodeEvent.NODE_FAILED,
            payload={"error": str(exc)},
        )
        raise


def _process_synthesis_ready_node(
    conn: sqlite3.Connection,
    *,
    node_id: str,
    model: ResearchModelClient,
    config: WorkerConfig,
) -> None:
    node = db.get_node_detail(conn, node_id)
    run = db.get_run(conn, node.run_id)

    db.apply_node_event(
        conn,
        node_id=node.node_id,
        event=NodeEvent.CHILDREN_COMPLETED,
    )

    try:
        synthesis_context = BranchSynthesisContext(
            company=run.company,
            topic=node.topic,
            analysis=node.analysis or "",
            child_summaries=_child_summaries(conn, node.node_id),
        )
        synthesis = _record_text_model_call(
            conn,
            run_id=node.run_id,
            node_id=node.node_id,
            call_type="branch_synthesize",
            input_payload=_jsonable(synthesis_context),
            call=lambda: model.branch_synthesize(synthesis_context),
            config=config,
        )
        db.store_branch_synthesis(
            conn,
            node_id=node.node_id,
            branch_synthesis=synthesis,
        )
        db.apply_node_event(
            conn,
            node_id=node.node_id,
            event=NodeEvent.SYNTHESIS_SUCCEEDED,
        )
    except Exception as exc:
        db.apply_node_event(
            conn,
            node_id=node.node_id,
            event=NodeEvent.NODE_FAILED,
            payload={"error": str(exc)},
        )
        raise


def _spawn_child_threads(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    parent_id: str,
    parent_depth: int,
    candidates: list[ThreadCandidate],
    config: WorkerConfig,
) -> int:
    if parent_depth >= config.max_depth:
        return 0

    count = 0
    for candidate in candidates:
        if db.node_count(conn, run_id) >= config.max_total_nodes:
            break
        if not candidate.should_spawn_node:
            continue
        _create_candidate_node(
            conn,
            run_id=run_id,
            parent_id=parent_id,
            candidate=candidate,
        )
        count += 1
    return count


def _spawn_discovered_threads(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    parent_id: str | None,
    sibling_depth: int,
    candidates: list[ThreadCandidate],
    config: WorkerConfig,
) -> int:
    if sibling_depth > config.max_depth:
        return 0

    count = 0
    for candidate in candidates:
        if db.node_count(conn, run_id) >= config.max_total_nodes:
            break
        if not candidate.should_spawn_node:
            continue
        _create_candidate_node(
            conn,
            run_id=run_id,
            parent_id=parent_id,
            candidate=candidate,
        )
        count += 1
    return count


def _create_candidate_node(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    parent_id: str | None,
    candidate: ThreadCandidate,
) -> db.NodeRecord:
    return db.create_node(
        conn,
        run_id=run_id,
        parent_id=parent_id,
        topic=candidate.topic,
        description=candidate.description,
        material=candidate.material,
        priority=candidate.queue_priority,
        resolution_state=candidate.resolution_state.value,
        evidence_basis=candidate.evidence_basis.value,
        triggering_text_span=candidate.triggering_text_span,
        why_unresolved=candidate.why_unresolved,
        investigation_brief=candidate.investigation_brief,
    )


def _ancestor_context(
    conn: sqlite3.Connection,
    node: db.NodeDetail,
) -> tuple[AncestorContext, ...]:
    ancestors: list[AncestorContext] = []
    parent_id = node.parent_id

    while parent_id is not None:
        parent = db.get_node_detail(conn, parent_id)
        ancestors.append(
            AncestorContext(
                topic=parent.topic,
                investigation_brief=parent.investigation_brief,
                abstract=parent.abstract or "",
            )
        )
        parent_id = parent.parent_id

    ancestors.reverse()
    return tuple(ancestors)


def _child_summaries(
    conn: sqlite3.Connection,
    node_id: str,
) -> tuple[ChildSummary, ...]:
    summaries: list[ChildSummary] = []
    for child in db.child_nodes(conn, node_id):
        if child.status == NodeState.REJECTED:
            continue
        if child.status == NodeState.FAILED:
            summaries.append(
                ChildSummary(
                    topic=child.topic,
                    summary=f"[investigation failed: {child.topic}]",
                    failed=True,
                )
            )
            continue
        summaries.append(
            ChildSummary(
                topic=child.topic,
                summary=child.branch_synthesis or child.abstract or "",
            )
        )
    return tuple(summaries)


def _source_material_contexts(
    search_provider: SearchProvider | None,
    *,
    company: str,
    node: db.NodeDetail,
) -> tuple[SourceMaterialContext, ...]:
    if search_provider is None:
        return ()

    sources = search_provider.search(
        company=company,
        query=f"{node.topic}\n{node.investigation_brief}",
        max_results=5,
    )
    return tuple(SourceMaterialContext.from_source(source) for source in sources)


def _record_structured_model_call(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    node_id: str | None,
    call_type: str,
    input_payload: dict[str, Any],
    call: Callable[[], T],
    config: WorkerConfig,
) -> T:
    call_id = db.create_model_call(
        conn,
        run_id=run_id,
        node_id=node_id,
        call_type=call_type,
        model_name=config.model_name,
        prompt_version=config.prompt_version,
        input_payload=input_payload,
    )
    try:
        output = call()
    except Exception as exc:
        db.complete_model_call(conn, call_id=call_id, error=str(exc))
        raise

    db.complete_model_call(
        conn,
        call_id=call_id,
        output_payload=_jsonable(output),
    )
    return output


def _record_text_model_call(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    node_id: str | None,
    call_type: str,
    input_payload: dict[str, Any],
    call: Callable[[], str],
    config: WorkerConfig,
) -> str:
    call_id = db.create_model_call(
        conn,
        run_id=run_id,
        node_id=node_id,
        call_type=call_type,
        model_name=config.model_name,
        prompt_version=config.prompt_version,
        input_payload=input_payload,
    )
    try:
        output = call()
    except Exception as exc:
        db.complete_model_call(conn, call_id=call_id, error=str(exc))
        raise

    db.complete_model_call(conn, call_id=call_id, output_text=output)
    return output


def _jsonable(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, dict):
        return value
    raise TypeError(f"Cannot serialize model call payload: {type(value)!r}")
