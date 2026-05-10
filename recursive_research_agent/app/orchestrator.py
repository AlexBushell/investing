"""Serial worker for the recursive research lifecycle.

This is the first vertical slice of orchestration. It intentionally excludes
deduplication, findings retrieval, rendering, and real search/model providers.
The goal is to prove that persisted nodes can move through the lifecycle using
the FSM and typed model boundary.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, TypeVar

from app import db
from app import dedup
from app.fsm import NodeEvent, NodeState
from app.llm import (
    AncestorContext,
    BranchSynthesisContext,
    ChildSummary,
    DedupCheckContext,
    DedupExistingThreadContext,
    DeepDiveContext,
    ResearchModelClient,
    SiblingConsolidationContext,
    SourceMaterialContext,
)
from app.schemas import ThreadCandidate
from app.schemas import SearchPlanOutput, SearchQuery
from app.search import SearchProvider


@dataclass(frozen=True)
class WorkerConfig:
    max_depth: int = 8
    max_total_nodes: int = 500
    max_wall_clock_seconds: float | None = None
    model_name: str = "fake-model"
    prompt_version: str = "fake-v1"
    search_results_per_node: int = 5
    search_queries_per_node: int = 4
    log_callback: Callable[[str], None] | None = None


T = TypeVar("T")
ProgressCallback = Callable[[sqlite3.Connection, str], None]


def start_run(
    conn: sqlite3.Connection,
    *,
    company: str,
    model: ResearchModelClient,
    config: WorkerConfig | None = None,
    progress_callback: ProgressCallback | None = None,
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
        model=model,
        config=config,
    )

    for brief in scope.root_threads[: config.max_total_nodes]:
        db.create_node(
            conn,
            run_id=run.run_id,
            topic=brief.topic,
            description=brief.description,
            priority=brief.priority,
            investigation_brief=brief.investigation_brief,
        )

    if progress_callback is not None:
        progress_callback(conn, run.run_id)

    return run


def run_to_completion(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    model: ResearchModelClient,
    search_provider: SearchProvider | None = None,
    config: WorkerConfig | None = None,
    progress_callback: ProgressCallback | None = None,
) -> db.RunRecord:
    """Process a run until no work remains."""

    config = config or WorkerConfig()
    deadline = _deadline_for_config(config)
    recovered = db.recover_transitional_nodes(conn, run_id=run_id)
    if recovered and progress_callback is not None:
        progress_callback(conn, run_id)

    while process_next_action(
        conn,
        run_id=run_id,
        model=model,
        search_provider=search_provider,
        config=config,
        progress_callback=progress_callback,
        deadline=deadline,
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
    progress_callback: ProgressCallback | None = None,
    deadline: float | None = None,
) -> bool:
    """Process one pending or synthesis-ready node.

    Returns true when work was performed. Returns false when the run has no
    remaining open nodes, after marking the run complete.
    """

    config = config or WorkerConfig()
    if _deadline_reached(deadline):
        return False

    pending = db.next_pending_node(conn, run_id=run_id)
    if pending is not None:
        if _short_circuit_duplicate_pending_node(
            conn,
            node_id=pending.node_id,
            model=model,
            config=config,
        ):
            if progress_callback is not None:
                progress_callback(conn, run_id)
            return True
        _process_pending_node(
            conn,
            node_id=pending.node_id,
            model=model,
            search_provider=search_provider,
            config=config,
        )
        if progress_callback is not None:
            progress_callback(conn, run_id)
        return True

    reference_ready = db.next_reference_ready_node(conn, run_id=run_id)
    if reference_ready is not None:
        db.apply_node_event(
            conn,
            node_id=reference_ready.node_id,
            event=NodeEvent.REFERENCE_COMPLETED,
        )
        if progress_callback is not None:
            progress_callback(conn, run_id)
        return True

    synthesis_ready = db.next_synthesis_ready_node(conn, run_id=run_id)
    if synthesis_ready is not None:
        _process_synthesis_ready_node(
            conn,
            node_id=synthesis_ready.node_id,
            model=model,
            config=config,
        )
        if progress_callback is not None:
            progress_callback(conn, run_id)
        return True

    if not db.has_open_nodes(conn, run_id):
        run = db.get_run(conn, run_id)
        if run.status != "complete":
            db.complete_run(conn, run_id)
            if progress_callback is not None:
                progress_callback(conn, run_id)
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
                conn,
                search_provider,
                model=model,
                run_id=node.run_id,
                company=run.company,
                node=node,
                max_results=config.search_results_per_node,
                max_queries=config.search_queries_per_node,
                config=config,
            ),
        )
        deep_dive = _record_structured_model_call(
            conn,
            run_id=node.run_id,
            node_id=node.node_id,
            call_type="deep_dive",
            input_payload=_jsonable(deep_dive_context),
            call=lambda: model.deep_dive(deep_dive_context),
            model=model,
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
                model=model,
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
            model=model,
            config=config,
        )
        child_candidates = _consolidate_sibling_candidates(
            conn,
            run_id=node.run_id,
            node_id=node.node_id,
            model=model,
            company=run.company,
            parent_topic=node.topic,
            parent_brief=node.investigation_brief,
            candidates=reflect.child_threads,
            config=config,
        )
        child_count = _spawn_child_threads(
            conn,
            run_id=node.run_id,
            parent_id=node.node_id,
            parent_depth=node.depth,
            candidates=child_candidates,
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
        db.record_node_failure(conn, node_id=node.node_id, error=str(exc))
        db.apply_node_event(
            conn,
            node_id=node.node_id,
            event=NodeEvent.NODE_FAILED,
            payload={"error": str(exc)},
        )


def _short_circuit_duplicate_pending_node(
    conn: sqlite3.Connection,
    *,
    node_id: str,
    model: ResearchModelClient,
    config: WorkerConfig,
) -> bool:
    """Mark a pending duplicate node as a reference instead of investigating it."""

    node = db.get_node_detail(conn, node_id)
    existing_threads = dedup.existing_thread_candidates(
        conn,
        run_id=node.run_id,
        node_id=node.node_id,
    )
    if not existing_threads:
        return False

    dedup_context = DedupCheckContext(
        company=db.get_run(conn, node.run_id).company,
        candidate_topic=node.topic,
        candidate_brief=node.investigation_brief,
        existing_threads=tuple(
            DedupExistingThreadContext(
                node_id=thread.node_id,
                topic=thread.topic,
                investigation_brief=thread.investigation_brief,
                status=thread.status.value,
            )
            for thread in existing_threads
        ),
    )
    decision = _record_structured_model_call(
        conn,
        run_id=node.run_id,
        node_id=node.node_id,
        call_type="deduplicate_investigation",
        input_payload=_jsonable(dedup_context),
        call=lambda: model.deduplicate_investigation(dedup_context),
        model=model,
        config=config,
    )
    if not decision.should_reference or decision.canonical_node_id is None:
        return False

    canonical_node_ids = {thread.node_id for thread in existing_threads}
    if decision.canonical_node_id not in canonical_node_ids:
        raise ValueError(
            "Deduplication returned an invalid canonical_node_id: "
            f"{decision.canonical_node_id}"
        )

    db.mark_node_reference(
        conn,
        reference_node_id=node.node_id,
        canonical_node_id=decision.canonical_node_id,
        origin_brief=node.investigation_brief,
    )
    db.apply_node_event(
        conn,
        node_id=node.node_id,
        event=NodeEvent.MARK_REFERENCE,
        payload={
            "canonical_node_id": decision.canonical_node_id,
            "reasoning": decision.reasoning,
        },
    )

    canonical = db.get_node_detail(conn, decision.canonical_node_id)
    if canonical.status in {
        NodeState.COMPLETE,
        NodeState.FAILED,
        NodeState.REJECTED,
    }:
        db.apply_node_event(
            conn,
            node_id=node.node_id,
            event=NodeEvent.REFERENCE_COMPLETED,
        )
    return True


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
        db.record_node_failure(conn, node_id=node.node_id, error=str(exc))
        db.apply_node_event(
            conn,
            node_id=node.node_id,
            event=NodeEvent.NODE_FAILED,
            payload={"error": str(exc)},
        )


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


def _consolidate_sibling_candidates(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    node_id: str,
    model: ResearchModelClient,
    company: str,
    parent_topic: str,
    parent_brief: str,
    candidates: list[ThreadCandidate],
    config: WorkerConfig,
) -> list[ThreadCandidate]:
    if len(candidates) <= 1:
        return candidates

    context = SiblingConsolidationContext(
        company=company,
        parent_topic=parent_topic,
        parent_brief=parent_brief,
        child_threads=tuple(candidates),
    )
    output = _record_structured_model_call(
        conn,
        run_id=run_id,
        node_id=node_id,
        call_type="consolidate_siblings",
        input_payload=_jsonable(context),
        call=lambda: model.consolidate_siblings(context),
        model=model,
        config=config,
    )
    return output.child_threads


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
        reference = db.node_reference(conn, child.node_id)
        if reference is not None:
            canonical = db.get_node_detail(conn, reference["canonical_node_id"])
            if canonical.status == NodeState.FAILED:
                summaries.append(
                    ChildSummary(
                        topic=child.topic,
                        summary=f"[investigation failed: {canonical.topic}]",
                        failed=True,
                    )
                )
            else:
                summaries.append(
                    ChildSummary(
                        topic=child.topic,
                        summary=canonical.branch_synthesis or canonical.abstract or "",
                    )
                )
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
    conn: sqlite3.Connection,
    search_provider: SearchProvider | None,
    *,
    model: ResearchModelClient,
    run_id: str,
    company: str,
    node: db.NodeDetail,
    max_results: int = 5,
    max_queries: int = 3,
    config: WorkerConfig,
) -> tuple[SourceMaterialContext, ...]:
    if search_provider is None:
        return ()

    search_plan = _search_plan_for_node(
        conn,
        run_id=run_id,
        node=node,
        model=model,
        company=company,
        config=config,
    )
    queries = _approved_search_queries(
        search_plan,
        company=company,
        node=node,
        max_queries=max_queries,
    )

    sources = []
    seen: set[str] = set()
    per_query_limit = max(1, (max_results + len(queries) - 1) // len(queries))
    for planned_query in queries:
        _log_worker(
            config,
            f"search start query={planned_query.query!r}",
        )
        result_count = 0
        try:
            for source in search_provider.search(
                company=company,
                query=planned_query.query,
                max_results=per_query_limit,
            ):
                result_count += 1
                key = source.url or source.title
                normalized_key = key.lower()
                if normalized_key in seen:
                    continue
                seen.add(normalized_key)
                sources.append(source)
                if len(sources) >= max_results:
                    _log_worker(
                        config,
                        f"search end results={result_count} total_sources={len(sources)}",
                    )
                    return tuple(SourceMaterialContext.from_source(item) for item in sources)
        except Exception:
            _log_worker(config, f"search end status=error results={result_count}")
            raise
        else:
            _log_worker(
                config,
                f"search end results={result_count} total_sources={len(sources)}",
            )

    return tuple(SourceMaterialContext.from_source(source) for source in sources)


def _search_plan_for_node(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    node: db.NodeDetail,
    model: ResearchModelClient,
    company: str,
    config: WorkerConfig,
) -> SearchPlanOutput:
    try:
        return _record_structured_model_call(
            conn,
            run_id=run_id,
            node_id=node.node_id,
            call_type="search_plan",
            input_payload={
                "company": company,
                "topic": node.topic,
                "investigation_brief": node.investigation_brief,
            },
            call=lambda: model.search_plan(
                company=company,
                topic=node.topic,
                investigation_brief=node.investigation_brief,
            ),
            model=model,
            config=config,
        )
    except Exception:
        return SearchPlanOutput(
            queries=[
                SearchQuery(
                    query=f"{company} {node.topic} {node.investigation_brief}"[:400].rstrip(),
                    purpose="Fallback deterministic query after search planning failed.",
                    source_preference="any",
                    freshness_days=None,
                )
            ]
        )


def _approved_search_queries(
    search_plan: SearchPlanOutput,
    *,
    company: str,
    node: db.NodeDetail,
    max_queries: int,
) -> list[SearchQuery]:
    approved: list[SearchQuery] = []
    seen: set[str] = set()
    for candidate in search_plan.queries:
        query = " ".join(candidate.query.split())
        if not query:
            continue
        normalized = query.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        approved.append(
            SearchQuery(
                query=query[:400].rstrip(),
                purpose=candidate.purpose,
                source_preference=candidate.source_preference,
                freshness_days=candidate.freshness_days,
            )
        )
        if len(approved) >= max_queries:
            break

    if approved:
        return approved
    return [
        SearchQuery(
            query=f"{company} {node.topic} {node.investigation_brief}"[:400].rstrip(),
            purpose="Fallback deterministic query because the search plan was empty.",
            source_preference="any",
            freshness_days=None,
        )
    ]


def _record_structured_model_call(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    node_id: str | None,
    call_type: str,
    input_payload: dict[str, Any],
    call: Callable[[], T],
    model: ResearchModelClient,
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
    _log_worker(config, f"model call start type={call_type}")
    try:
        output = call()
    except Exception as exc:
        db.complete_model_call(
            conn,
            call_id=call_id,
            output_payload=_model_response_metadata_payload(model),
            output_text=_model_response_text(model),
            error=str(exc),
        )
        _log_worker(config, f"model call end type={call_type} status=error")
        raise

    db.complete_model_call(
        conn,
        call_id=call_id,
        output_payload=_with_model_response_metadata(
            _jsonable(output),
            model,
        ),
    )
    _model_response_text(model)
    _log_worker(config, f"model call end type={call_type} status=ok")
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
    _log_worker(config, f"model call start type={call_type}")
    try:
        output = call()
    except Exception as exc:
        db.complete_model_call(conn, call_id=call_id, error=str(exc))
        _log_worker(config, f"model call end type={call_type} status=error")
        raise

    db.complete_model_call(conn, call_id=call_id, output_text=output)
    _log_worker(config, f"model call end type={call_type} status=ok")
    return output


def _jsonable(value: Any) -> dict[str, Any]:
    normalized = _normalize_jsonable(value)
    if isinstance(normalized, dict):
        return normalized
    raise TypeError(f"Cannot serialize model call payload: {type(value)!r}")


def _normalize_jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "__dataclass_fields__"):
        return _normalize_jsonable(asdict(value))
    if isinstance(value, dict):
        return {key: _normalize_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_jsonable(item) for item in value]
    return value


def _with_model_response_metadata(
    output_payload: dict[str, Any],
    model: ResearchModelClient,
) -> dict[str, Any]:
    metadata_payload = _model_response_metadata_payload(model)
    if metadata_payload is None:
        return output_payload
    return {
        **output_payload,
        **metadata_payload,
    }


def _model_response_metadata_payload(
    model: ResearchModelClient,
) -> dict[str, Any] | None:
    pop_metadata = getattr(model, "pop_last_response_metadata", None)
    if pop_metadata is None:
        return None
    metadata = pop_metadata()
    if not metadata:
        return None
    return {
        "_model_response_metadata": metadata,
    }


def _model_response_text(model: ResearchModelClient) -> str | None:
    pop_response_text = getattr(model, "pop_last_response_text", None)
    if pop_response_text is None:
        return None
    response_text = pop_response_text()
    return response_text if isinstance(response_text, str) else None


def _deadline_for_config(config: WorkerConfig) -> float | None:
    if config.max_wall_clock_seconds is None:
        return None
    return time.monotonic() + max(config.max_wall_clock_seconds, 0.0)


def _deadline_reached(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline


def _log_worker(config: WorkerConfig, message: str) -> None:
    if config.log_callback is not None:
        config.log_callback(message)
