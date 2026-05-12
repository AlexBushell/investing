"""Command line interface for the recursive research backend."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sqlite3
import tomllib

from app import db
from app.llm import DeepDiveContext, SourceMaterialContext
from app.llm import (
    FakeModelClient,
    OllamaGenerateClient,
    OllamaModelClient,
    OpenRouterModelClient,
)
from app.fsm import NodeEvent
from app.orchestrator import WorkerConfig, run_to_completion, start_run
from app.render import write_audit_markdown, write_dossier_markdown
from app.search import (
    BraveSearchProvider,
    CompositeSearchProvider,
    DirectorySearchProvider,
    SearchProvider,
    TavilySearchProvider,
    source_from_file,
)


DEFAULT_DB_PATH = Path("data") / "research.sqlite"
DEFAULT_OUTPUTS_DIR = Path("outputs") / "runs"
DEFAULT_SETTINGS_PATH = Path("research.toml")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _apply_settings_profile(args)
    return args.func(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="research",
        description="Recursive research agent backend CLI.",
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help=f"SQLite database path. Default: {DEFAULT_DB_PATH}",
    )

    subparsers = parser.add_subparsers(required=True)

    init_db = subparsers.add_parser("init-db", help="Initialize the database.")
    init_db.set_defaults(func=cmd_init_db)

    run = subparsers.add_parser(
        "run",
        aliases=["fake-run"],
        help="Run the recursive worker against local source data with the fake model.",
    )
    run.add_argument("company", help="Company name.")
    run.add_argument(
        "--outputs-dir",
        default=str(DEFAULT_OUTPUTS_DIR),
        help=f"Run artifact output directory. Default: {DEFAULT_OUTPUTS_DIR}",
    )
    run.add_argument("--max-depth", type=int, default=8)
    run.add_argument("--max-total-nodes", type=int, default=500)
    run.add_argument("--max-seconds", type=float)
    run.add_argument(
        "--source-dir",
        help="Optional local directory of .md/.txt source files for deep-dives.",
    )
    run.set_defaults(func=cmd_run)

    resume = subparsers.add_parser(
        "resume",
        help="Resume a fake-model run from persisted state.",
    )
    resume.add_argument("run_id", help="Run id to resume.")
    resume.add_argument(
        "--outputs-dir",
        default=str(DEFAULT_OUTPUTS_DIR),
        help=f"Run artifact output directory. Default: {DEFAULT_OUTPUTS_DIR}",
    )
    resume.add_argument("--max-depth", type=int, default=8)
    resume.add_argument("--max-total-nodes", type=int, default=500)
    resume.add_argument("--max-seconds", type=float)
    resume.add_argument(
        "--source-dir",
        help="Optional local directory of .md/.txt source files for deep-dives.",
    )
    resume.set_defaults(func=cmd_resume)

    render = subparsers.add_parser("render", help="Render dossier markdown.")
    render.add_argument("run_id", help="Run id to render.")
    render.add_argument(
        "--output",
        help="Output markdown path. Defaults to outputs/runs/<run_id>/dossier.md.",
    )
    render.set_defaults(func=cmd_render)

    audit = subparsers.add_parser("audit", help="Render audit markdown.")
    audit.add_argument("run_id", help="Run id to render.")
    audit.add_argument(
        "--output",
        help="Output markdown path. Defaults to outputs/runs/<run_id>/audit.md.",
    )
    audit.set_defaults(func=cmd_audit)

    run_summary = subparsers.add_parser(
        "run-summary",
        help="Print a compact operational summary for one persisted run.",
    )
    run_summary.add_argument("run_id", help="Run id to inspect.")
    run_summary.set_defaults(func=cmd_run_summary)

    model_calls = subparsers.add_parser(
        "model-calls",
        help="Summarize model calls for a run, including Ollama timing metadata.",
    )
    model_calls.add_argument("run_id", help="Run id to inspect.")
    model_calls.set_defaults(func=cmd_model_calls)

    model_call = subparsers.add_parser(
        "model-call",
        help="Show one persisted model call input/output for prompt debugging.",
    )
    model_call.add_argument("call_id", help="Model call id to inspect.")
    model_call.add_argument(
        "--raw",
        action="store_true",
        help="Print a single JSON object instead of the readable report.",
    )
    model_call.set_defaults(func=cmd_model_call)

    ollama_smoke = subparsers.add_parser(
        "ollama-smoke",
        help="Smoke-test Ollama structured output with a tiny schema.",
    )
    ollama_smoke.add_argument(
        "--model",
        default="gemma4:latest",
        help="Ollama model name. Default: gemma4:latest",
    )
    ollama_smoke.add_argument(
        "--base-url",
        default="http://localhost:11434",
        help="Ollama base URL. Default: http://localhost:11434",
    )
    ollama_smoke.add_argument(
        "--temperature",
        type=float,
        default=1.0,
        help="Model temperature. Default: 1.0",
    )
    ollama_smoke.add_argument(
        "--num-predict",
        type=int,
        default=4096,
        help="Maximum generated tokens. Default: 4096",
    )
    ollama_smoke.add_argument(
        "--think",
        action="store_true",
        help="Enable Ollama/Gemma thinking mode for the smoke call.",
    )
    ollama_smoke.add_argument(
        "--keep-alive",
        default="5m",
        help="How long Ollama should keep the model loaded. Default: 5m",
    )
    ollama_smoke.add_argument(
        "--timeout-seconds",
        type=float,
        default=120.0,
        help="HTTP timeout in seconds. Default: 120",
    )
    ollama_smoke.add_argument(
        "--company",
        default="Example Co",
        help="Company name for the smoke prompt. Default: Example Co",
    )
    ollama_smoke.set_defaults(func=cmd_ollama_smoke)

    ollama_scope = subparsers.add_parser(
        "ollama-scope",
        help="Run the real Ollama scope call and print structured JSON.",
    )
    _add_ollama_args(ollama_scope)
    ollama_scope.add_argument("company", help="Company name.")
    ollama_scope.set_defaults(func=cmd_ollama_scope)

    ollama_scope_run = subparsers.add_parser(
        "ollama-scope-run",
        help="Create a run using real Ollama scope output and write audit markdown.",
    )
    _add_ollama_args(ollama_scope_run)
    ollama_scope_run.add_argument("company", help="Company name.")
    ollama_scope_run.add_argument(
        "--outputs-dir",
        default=str(DEFAULT_OUTPUTS_DIR),
        help=f"Run artifact output directory. Default: {DEFAULT_OUTPUTS_DIR}",
    )
    ollama_scope_run.set_defaults(func=cmd_ollama_scope_run)

    ollama_deep_dive = subparsers.add_parser(
        "ollama-deep-dive-smoke",
        help=(
            "Create a real Ollama scope run, deep-dive the first root node, "
            "and write audit/dossier markdown without reflecting."
        ),
    )
    _add_ollama_args(ollama_deep_dive)
    ollama_deep_dive.add_argument("company", help="Company name.")
    ollama_deep_dive.add_argument(
        "--outputs-dir",
        default=str(DEFAULT_OUTPUTS_DIR),
        help=f"Run artifact output directory. Default: {DEFAULT_OUTPUTS_DIR}",
    )
    ollama_deep_dive.add_argument(
        "--source-file",
        action="append",
        default=[],
        help=(
            "Local text/markdown source file to supply to the deep-dive. "
            "May be passed multiple times."
        ),
    )
    ollama_deep_dive.set_defaults(func=cmd_ollama_deep_dive_smoke)

    ollama_reflect = subparsers.add_parser(
        "ollama-reflect-smoke",
        help=(
            "Create a real Ollama scope run, source-backed deep-dive the first "
            "root node, reflect it, spawn child nodes, and write artifacts."
        ),
    )
    _add_ollama_args(ollama_reflect)
    ollama_reflect.add_argument("company", help="Company name.")
    ollama_reflect.add_argument(
        "--outputs-dir",
        default=str(DEFAULT_OUTPUTS_DIR),
        help=f"Run artifact output directory. Default: {DEFAULT_OUTPUTS_DIR}",
    )
    ollama_reflect.add_argument(
        "--source-file",
        action="append",
        default=[],
        help=(
            "Local text/markdown source file to supply to the deep-dive. "
            "May be passed multiple times."
        ),
    )
    ollama_reflect.set_defaults(func=cmd_ollama_reflect_smoke)

    ollama_run = subparsers.add_parser(
        "ollama-run",
        help="Run a guarded real Ollama recursive pass using configured sources.",
    )
    _add_ollama_args(ollama_run, profiled=True)
    ollama_run.add_argument("company", help="Company name.")
    _add_run_source_args(ollama_run, profiled=True)
    _add_profile_args(ollama_run)
    ollama_run.set_defaults(func=cmd_ollama_run)

    openrouter_run = subparsers.add_parser(
        "openrouter-run",
        help=(
            "Run a guarded recursive pass using an OpenRouter model and "
            "configured local/web sources."
        ),
    )
    _add_openrouter_args(openrouter_run, profiled=True)
    openrouter_run.add_argument("company", help="Company name.")
    _add_run_source_args(openrouter_run, profiled=True)
    _add_profile_args(openrouter_run)
    openrouter_run.set_defaults(func=cmd_openrouter_run)

    return parser


def cmd_init_db(args: argparse.Namespace) -> int:
    conn = db.connect(args.db)
    try:
        db.initialize_database(conn)
    finally:
        conn.close()
    print(f"Initialized database: {args.db}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    conn = db.connect(args.db)
    try:
        db.initialize_database(conn)
        model = FakeModelClient()
        outputs_dir = Path(args.outputs_dir)
        run = start_run(
            conn,
            company=args.company,
            model=model,
            config=WorkerConfig(
                max_depth=args.max_depth,
                max_total_nodes=args.max_total_nodes,
                max_wall_clock_seconds=args.max_seconds,
            ),
            progress_callback=_audit_progress_callback(outputs_dir),
        )
        completed = run_to_completion(
            conn,
            run_id=run.run_id,
            model=model,
            search_provider=(
                DirectorySearchProvider(args.source_dir)
                if args.source_dir
                else None
            ),
            config=WorkerConfig(
                max_depth=args.max_depth,
                max_total_nodes=args.max_total_nodes,
                max_wall_clock_seconds=args.max_seconds,
            ),
            progress_callback=_audit_progress_callback(outputs_dir),
        )

        run_dir = Path(args.outputs_dir) / completed.run_id
        audit_path = write_audit_markdown(
            conn,
            run_id=completed.run_id,
            output_path=run_dir / "audit.md",
        )
        dossier_path = write_dossier_markdown(
            conn,
            run_id=completed.run_id,
            output_path=run_dir / "dossier.md",
        )
    finally:
        conn.close()

    _print_run_result(completed, audit_path, dossier_path)
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    conn = db.connect(args.db)
    try:
        db.initialize_database(conn)
        model = FakeModelClient()
        completed = run_to_completion(
            conn,
            run_id=args.run_id,
            model=model,
            search_provider=(
                DirectorySearchProvider(args.source_dir)
                if args.source_dir
                else None
            ),
            config=WorkerConfig(
                max_depth=args.max_depth,
                max_total_nodes=args.max_total_nodes,
                max_wall_clock_seconds=args.max_seconds,
            ),
            progress_callback=_audit_progress_callback(Path(args.outputs_dir)),
        )
        run_dir = Path(args.outputs_dir) / completed.run_id
        audit_path = write_audit_markdown(
            conn,
            run_id=completed.run_id,
            output_path=run_dir / "audit.md",
        )
        dossier_path = write_dossier_markdown(
            conn,
            run_id=completed.run_id,
            output_path=run_dir / "dossier.md",
        )
    finally:
        conn.close()

    _print_run_result(completed, audit_path, dossier_path)
    return 0


def _print_run_result(completed, audit_path: Path, dossier_path: Path) -> None:
    if completed.status == "complete":
        print(f"Run complete: {completed.run_id}")
    else:
        print(f"Run paused: {completed.run_id}")
        print(f"Status: {completed.status}")
    print(f"Audit: {audit_path}")
    print(f"Dossier: {dossier_path}")


def cmd_render(args: argparse.Namespace) -> int:
    conn = db.connect(args.db)
    try:
        output_path = Path(args.output) if args.output else _default_dossier_path(
            args.run_id
        )
        path = write_dossier_markdown(
            conn,
            run_id=args.run_id,
            output_path=output_path,
        )
    finally:
        conn.close()
    print(f"Dossier: {path}")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    conn = db.connect(args.db)
    try:
        output_path = Path(args.output) if args.output else _default_audit_path(
            args.run_id
        )
        path = write_audit_markdown(
            conn,
            run_id=args.run_id,
            output_path=output_path,
        )
    finally:
        conn.close()
    print(f"Audit: {path}")
    return 0


def cmd_run_summary(args: argparse.Namespace) -> int:
    conn = db.connect(args.db)
    try:
        db.initialize_database(conn)
        run = _run_summary_row(conn, args.run_id)
        if run is None:
            raise SystemExit(f"No run found: {args.run_id}")
        status_counts = _run_node_status_counts(conn, args.run_id)
        model_rows = conn.execute(
            """
            SELECT DISTINCT model_name, prompt_version
            FROM model_calls
            WHERE run_id = ?
            ORDER BY model_name ASC, prompt_version ASC
            """,
            (args.run_id,),
        ).fetchall()
        call_type_rows = conn.execute(
            """
            SELECT call_type, COUNT(*) AS count
            FROM model_calls
            WHERE run_id = ?
            GROUP BY call_type
            ORDER BY call_type ASC
            """,
            (args.run_id,),
        ).fetchall()
        error_count_row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM model_calls
            WHERE run_id = ? AND error IS NOT NULL
            """,
            (args.run_id,),
        ).fetchone()
        node_failure_row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM node_failures nf
            JOIN nodes n ON n.node_id = nf.node_id
            WHERE n.run_id = ?
            """,
            (args.run_id,),
        ).fetchone()
    finally:
        conn.close()

    audit_path = _default_audit_path(args.run_id)
    dossier_path = _default_dossier_path(args.run_id)
    total_nodes = sum(status_counts.values())

    print(f"Run ID: {run['run_id']}")
    print(f"Company: {run['company']}")
    print(f"Status: {run['status']}")
    print(f"Started: {run['started_at']}")
    print(f"Completed: {run['completed_at'] or ''}")
    print(f"Parent Run ID: {run['parent_run_id'] or ''}")
    print(f"Total Nodes: {total_nodes}")
    print(f"Model Calls: {sum(int(row['count']) for row in call_type_rows)}")
    print(f"Model Call Errors: {int(error_count_row['count'])}")
    print(f"Node Failures Recorded: {int(node_failure_row['count'])}")
    print()
    print("Node Status Counts:")
    if status_counts:
        for status, count in sorted(status_counts.items()):
            print(f"- {status}: {count}")
    else:
        print("- none")
    print()
    print("Model Variants:")
    if model_rows:
        for row in model_rows:
            print(f"- {row['model_name']} | {row['prompt_version']}")
    else:
        print("- none")
    print()
    print("Model Call Types:")
    if call_type_rows:
        for row in call_type_rows:
            print(f"- {row['call_type']}: {row['count']}")
    else:
        print("- none")
    print()
    print("Artifacts:")
    print(f"- Audit: {audit_path}")
    print(f"- Dossier: {dossier_path}")
    return 0


def cmd_ollama_smoke(args: argparse.Namespace) -> int:
    client = OllamaGenerateClient(
        model_name=args.model,
        base_url=args.base_url,
        temperature=args.temperature,
        num_predict=args.num_predict,
        enable_thinking=args.think,
        keep_alive=args.keep_alive,
        timeout_seconds=args.timeout_seconds,
    )
    output = client.smoke_structured_output(company=args.company)
    print("Ollama structured output smoke test succeeded.")
    print(output.model_dump_json(indent=2))
    return 0


def cmd_ollama_scope(args: argparse.Namespace) -> int:
    model = _ollama_model_from_args(args)
    output = model.scope(args.company)
    print(output.model_dump_json(indent=2))
    return 0


def cmd_ollama_scope_run(args: argparse.Namespace) -> int:
    conn = db.connect(args.db)
    try:
        db.initialize_database(conn)
        model = _ollama_model_from_args(args)
        run = start_run(
            conn,
            company=args.company,
            model=model,
            config=WorkerConfig(
                model_name=args.model,
                prompt_version="scope-v1",
            ),
            progress_callback=_audit_progress_callback(Path(args.outputs_dir)),
        )
        run_dir = Path(args.outputs_dir) / run.run_id
        audit_path = write_audit_markdown(
            conn,
            run_id=run.run_id,
            output_path=run_dir / "audit.md",
        )
    finally:
        conn.close()

    print(f"Scope run created: {run.run_id}")
    print(f"Audit: {audit_path}")
    return 0


def cmd_ollama_deep_dive_smoke(args: argparse.Namespace) -> int:
    conn = db.connect(args.db)
    try:
        db.initialize_database(conn)
        model = _ollama_model_from_args(args)
        config = WorkerConfig(
            model_name=args.model,
            prompt_version="deep-dive-v1",
        )
        run = start_run(
            conn,
            company=args.company,
            model=model,
            config=config,
        )
        node = db.first_pending_node(conn, run_id=run.run_id)
        if node is None:
            raise RuntimeError("Scope produced no pending nodes.")

        db.apply_node_event(
            conn,
            node_id=node.node_id,
            event=NodeEvent.START_INVESTIGATION,
        )
        deep_dive = model.deep_dive(
            DeepDiveContext(
                company=args.company,
                topic=node.topic,
                investigation_brief=node.investigation_brief,
                source_materials=tuple(
                    SourceMaterialContext.from_source(source_from_file(path))
                    for path in args.source_file
                ),
            )
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
        db.apply_node_event(
            conn,
            node_id=node.node_id,
            event=NodeEvent.REFLECT_FOUND_NO_CHILDREN,
            payload={"smoke_test": True},
        )

        run_dir = Path(args.outputs_dir) / run.run_id
        audit_path = write_audit_markdown(
            conn,
            run_id=run.run_id,
            output_path=run_dir / "audit.md",
        )
        dossier_path = write_dossier_markdown(
            conn,
            run_id=run.run_id,
            output_path=run_dir / "dossier.md",
        )
    finally:
        conn.close()

    print(f"Deep-dive smoke run created: {run.run_id}")
    print(f"Investigated node: {node.topic}")
    print(f"Audit: {audit_path}")
    print(f"Dossier: {dossier_path}")
    return 0


def cmd_ollama_reflect_smoke(args: argparse.Namespace) -> int:
    conn = db.connect(args.db)
    try:
        db.initialize_database(conn)
        model = _ollama_model_from_args(args)
        config = WorkerConfig(
            model_name=args.model,
            prompt_version="reflect-v1",
        )
        run = start_run(
            conn,
            company=args.company,
            model=model,
            config=config,
        )
        node = db.first_pending_node(conn, run_id=run.run_id)
        if node is None:
            raise RuntimeError("Scope produced no pending nodes.")

        db.apply_node_event(
            conn,
            node_id=node.node_id,
            event=NodeEvent.START_INVESTIGATION,
        )
        deep_dive = model.deep_dive(
            DeepDiveContext(
                company=args.company,
                topic=node.topic,
                investigation_brief=node.investigation_brief,
                source_materials=tuple(
                    SourceMaterialContext.from_source(source_from_file(path))
                    for path in args.source_file
                ),
            )
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

        reflect = model.reflect(deep_dive.analysis)
        child_count = 0
        for candidate in reflect.child_threads:
            if not candidate.should_spawn_node:
                continue
            db.create_node(
                conn,
                run_id=run.run_id,
                parent_id=node.node_id,
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
            child_count += 1

        db.apply_node_event(
            conn,
            node_id=node.node_id,
            event=(
                NodeEvent.REFLECT_FOUND_CHILDREN
                if child_count
                else NodeEvent.REFLECT_FOUND_NO_CHILDREN
            ),
            payload={"child_count": child_count, "smoke_test": True},
        )

        run_dir = Path(args.outputs_dir) / run.run_id
        audit_path = write_audit_markdown(
            conn,
            run_id=run.run_id,
            output_path=run_dir / "audit.md",
        )
        dossier_path = write_dossier_markdown(
            conn,
            run_id=run.run_id,
            output_path=run_dir / "dossier.md",
        )
    finally:
        conn.close()

    print(f"Reflect smoke run created: {run.run_id}")
    print(f"Reflected node: {node.topic}")
    print(f"Spawned children: {child_count}")
    print(f"Audit: {audit_path}")
    print(f"Dossier: {dossier_path}")
    return 0


def cmd_ollama_run(args: argparse.Namespace) -> int:
    search_provider = _search_provider_from_args(args)
    _log(
        "Starting ollama-run "
        f"company={args.company!r} model={args.model} keep_alive={args.keep_alive}"
    )
    conn = db.connect(args.db)
    try:
        db.initialize_database(conn)
        model = _ollama_model_from_args(args)
        config = WorkerConfig(
            max_depth=args.max_depth,
            max_total_nodes=args.max_total_nodes,
            model_name=args.model,
            prompt_version="ollama-run-v1",
            search_results_per_node=args.search_results,
            search_queries_per_node=args.search_queries,
            log_callback=_log,
        )
        run = start_run(
            conn,
            company=args.company,
            model=model,
            config=config,
            progress_callback=_audit_progress_callback(Path(args.outputs_dir)),
        )
        completed = run_to_completion(
            conn,
            run_id=run.run_id,
            model=model,
            search_provider=search_provider,
            config=config,
            progress_callback=_audit_progress_callback(Path(args.outputs_dir)),
        )

        run_dir = Path(args.outputs_dir) / completed.run_id
        audit_path = write_audit_markdown(
            conn,
            run_id=completed.run_id,
            output_path=run_dir / "audit.md",
        )
        dossier_path = write_dossier_markdown(
            conn,
            run_id=completed.run_id,
            output_path=run_dir / "dossier.md",
        )
    finally:
        conn.close()

    _log(f"Finished ollama-run run_id={completed.run_id} status={completed.status}")
    print(f"Ollama run complete: {completed.run_id}")
    print(f"Status: {completed.status}")
    print(f"Audit: {audit_path}")
    print(f"Dossier: {dossier_path}")
    return 0


def cmd_openrouter_run(args: argparse.Namespace) -> int:
    search_provider = _search_provider_from_args(args, command_name="openrouter-run")
    if not args.openrouter_api_key:
        raise SystemExit(
            "openrouter-run requires --openrouter-api-key or OPENROUTER_API_KEY."
        )
    _log(
        "Starting openrouter-run "
        f"company={args.company!r} model={args.model}"
    )
    conn = db.connect(args.db)
    try:
        db.initialize_database(conn)
        model = _openrouter_model_from_args(args)
        config = WorkerConfig(
            max_depth=args.max_depth,
            max_total_nodes=args.max_total_nodes,
            model_name=args.model,
            prompt_version="openrouter-run-v1",
            search_results_per_node=args.search_results,
            search_queries_per_node=args.search_queries,
            log_callback=_log,
        )
        run = start_run(
            conn,
            company=args.company,
            model=model,
            config=config,
            progress_callback=_audit_progress_callback(Path(args.outputs_dir)),
        )
        completed = run_to_completion(
            conn,
            run_id=run.run_id,
            model=model,
            search_provider=search_provider,
            config=config,
            progress_callback=_audit_progress_callback(Path(args.outputs_dir)),
        )

        run_dir = Path(args.outputs_dir) / completed.run_id
        audit_path = write_audit_markdown(
            conn,
            run_id=completed.run_id,
            output_path=run_dir / "audit.md",
        )
        dossier_path = write_dossier_markdown(
            conn,
            run_id=completed.run_id,
            output_path=run_dir / "dossier.md",
        )
    finally:
        conn.close()

    _log(
        f"Finished openrouter-run run_id={completed.run_id} "
        f"status={completed.status}"
    )
    print(f"OpenRouter run complete: {completed.run_id}")
    print(f"Status: {completed.status}")
    print(f"Audit: {audit_path}")
    print(f"Dossier: {dossier_path}")
    return 0


def cmd_model_calls(args: argparse.Namespace) -> int:
    conn = db.connect(args.db)
    try:
        calls = db.model_calls(conn, run_id=args.run_id)
    finally:
        conn.close()

    if not calls:
        print(f"No model calls found for run: {args.run_id}")
        return 0

    print("Call ID | Call Type | Error | Load | Total | Eval Count | Started | Completed")
    print("--- | --- | --- | --- | --- | --- | --- | ---")
    for call in calls:
        metadata = _model_call_metadata(call.output_json)
        print(
            " | ".join(
                [
                    call.call_id,
                    call.call_type,
                    "yes" if call.error else "no",
                    _duration_ns(metadata.get("load_duration")),
                    _duration_ns(metadata.get("total_duration")),
                    str(metadata.get("eval_count") or ""),
                    call.started_at,
                    call.completed_at or "",
                ]
            )
        )
    return 0


def cmd_model_call(args: argparse.Namespace) -> int:
    conn = db.connect(args.db)
    try:
        call = db.model_call(conn, call_id=args.call_id)
    finally:
        conn.close()

    if call is None:
        raise SystemExit(f"No model call found: {args.call_id}")

    payload = _model_call_to_dict(call)
    if args.raw:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"Call ID: {call.call_id}")
    print(f"Run ID: {call.run_id}")
    print(f"Node ID: {call.node_id or ''}")
    print(f"Call Type: {call.call_type}")
    print(f"Model: {call.model_name}")
    print(f"Prompt Version: {call.prompt_version}")
    print(f"Started: {call.started_at}")
    print(f"Completed: {call.completed_at or ''}")
    print(f"Error: {'yes' if call.error else 'no'}")
    print()
    print("Input JSON:")
    print(_pretty_json_value(payload["input"]))
    if call.output_json:
        print()
        print("Output JSON:")
        print(_pretty_json_value(payload["output_json"]))
    if call.output_text:
        print()
        print("Output Text:")
        print(call.output_text)
    if call.error:
        print()
        print("Error Detail:")
        print(call.error)
    return 0


def _search_provider_from_args(
    args: argparse.Namespace,
    *,
    command_name: str = "ollama-run",
) -> SearchProvider:
    if args.search_results < 1:
        raise SystemExit("--search-results must be at least 1.")
    if args.search_queries < 1:
        raise SystemExit("--search-queries must be at least 1.")
    if args.freshness_days is not None and args.freshness_days < 0:
        raise SystemExit("--freshness-days must not be negative.")

    providers: list[SearchProvider] = []
    if args.source_dir:
        providers.append(DirectorySearchProvider(args.source_dir))
    if args.web_search == "brave":
        brave = BraveSearchProvider(
            api_key=args.brave_api_key,
            freshness_days=args.freshness_days,
        )
        if not brave.api_key:
            raise SystemExit(
                "--web-search brave requires --brave-api-key or BRAVE_SEARCH_API_KEY."
            )
        providers.append(brave)
    if args.web_search == "tavily":
        tavily = TavilySearchProvider(
            api_key=args.tavily_api_key,
            freshness_days=args.freshness_days,
        )
        if not tavily.api_key:
            raise SystemExit(
                "--web-search tavily requires --tavily-api-key or TAVILY_API_KEY."
            )
        providers.append(tavily)
    if not providers:
        raise SystemExit(
            f"{command_name} requires --source-dir and/or --web-search brave|tavily."
        )
    if len(providers) == 1:
        return providers[0]
    return CompositeSearchProvider(providers)


def _apply_settings_profile(args: argparse.Namespace) -> None:
    profile_name = getattr(args, "profile", None)
    command_name = getattr(getattr(args, "func", None), "__name__", None)
    defaults = _profile_defaults_for_command(command_name)
    if not defaults:
        return

    profile: dict[str, object] = {}
    if profile_name:
        settings_file = Path(getattr(args, "settings_file", DEFAULT_SETTINGS_PATH))
        profile = _load_profile(settings_file, profile_name)

    for key, default_value in defaults.items():
        current_value = getattr(args, key, None)
        if current_value is not None:
            continue
        if key in profile:
            setattr(args, key, profile[key])
        else:
            setattr(args, key, default_value)

    _apply_profile_postprocessing(args)


def _load_profile(settings_file: Path, profile_name: str) -> dict[str, object]:
    if not settings_file.exists():
        raise SystemExit(
            f"Profile {profile_name!r} requested, but settings file was not found: "
            f"{settings_file}"
        )
    try:
        data = tomllib.loads(settings_file.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise SystemExit(
            f"Settings file is not valid TOML: {settings_file}: {exc}"
        ) from exc

    profiles = data.get("profiles")
    if not isinstance(profiles, dict):
        raise SystemExit(
            f"Settings file does not define a [profiles] table: {settings_file}"
        )
    profile = profiles.get(profile_name)
    if not isinstance(profile, dict):
        raise SystemExit(
            f"Profile {profile_name!r} was not found in settings file: {settings_file}"
        )
    return dict(profile)


def _profile_defaults_for_command(command_name: str | None) -> dict[str, object]:
    common = {
        "source_dir": None,
        "web_search": None,
        "brave_api_key": None,
        "tavily_api_key": None,
        "freshness_days": 730,
        "search_results": 5,
        "search_queries": 4,
        "outputs_dir": str(DEFAULT_OUTPUTS_DIR),
        "max_depth": 1,
        "max_total_nodes": 3,
    }
    if command_name == "cmd_ollama_run":
        return {
            **common,
            "model": "gemma4:latest",
            "base_url": "http://localhost:11434",
            "temperature": 1.0,
            "num_predict": 4096,
            "think": False,
            "keep_alive": "5m",
            "timeout_seconds": 120.0,
        }
    if command_name == "cmd_openrouter_run":
        return {
            **common,
            "base_url": "https://openrouter.ai/api/v1",
            "openrouter_api_key": os.environ.get("OPENROUTER_API_KEY"),
            "temperature": 1.0,
            "num_predict": 4096,
            "timeout_seconds": 120.0,
            "openrouter_title": "recursive-research-agent",
            "openrouter_referer": None,
            "openrouter_providers": [],
            "openrouter_no_fallbacks": False,
            "openrouter_require_parameters": False,
            "openrouter_response_format": "json_schema",
            "openrouter_max_transient_retries": 3,
            "openrouter_retry_base_delay_seconds": 1.0,
        }
    return {}


def _apply_profile_postprocessing(args: argparse.Namespace) -> None:
    providers = getattr(args, "openrouter_providers", None)
    if isinstance(providers, str):
        args.openrouter_providers = [providers]


def _add_profile_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--profile",
        help="Named profile from research.toml to apply before CLI overrides.",
    )
    parser.add_argument(
        "--settings-file",
        default=str(DEFAULT_SETTINGS_PATH),
        help=(
            "TOML settings file containing named profiles. "
            f"Default: {DEFAULT_SETTINGS_PATH}"
        ),
    )


def _add_ollama_args(
    parser: argparse.ArgumentParser,
    *,
    profiled: bool = False,
) -> None:
    parser.add_argument(
        "--model",
        default=None if profiled else "gemma4:latest",
        help="Ollama model name. Default: gemma4:latest",
    )
    parser.add_argument(
        "--base-url",
        default=None if profiled else "http://localhost:11434",
        help="Ollama base URL. Default: http://localhost:11434",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=None if profiled else 1.0,
        help="Model temperature. Default: 1.0",
    )
    parser.add_argument(
        "--num-predict",
        type=int,
        default=None if profiled else 4096,
        help="Maximum generated tokens. Default: 4096",
    )
    parser.add_argument(
        "--think",
        action="store_true",
        default=None if profiled else False,
        help="Enable Ollama/Gemma thinking mode.",
    )
    parser.add_argument(
        "--keep-alive",
        default=None if profiled else "5m",
        help="How long Ollama should keep the model loaded. Default: 5m",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=None if profiled else 120.0,
        help="HTTP timeout in seconds. Default: 120",
    )


def _add_openrouter_args(
    parser: argparse.ArgumentParser,
    *,
    profiled: bool = False,
) -> None:
    parser.add_argument(
        "--model",
        required=True,
        help=(
            "OpenRouter model id, for example anthropic/claude-3.7-sonnet "
            "or openai/gpt-4.1."
        ),
    )
    parser.add_argument(
        "--base-url",
        default=None if profiled else "https://openrouter.ai/api/v1",
        help="OpenRouter API base URL. Default: https://openrouter.ai/api/v1",
    )
    parser.add_argument(
        "--openrouter-api-key",
        default=None if profiled else os.environ.get("OPENROUTER_API_KEY"),
        help="OpenRouter API key. Defaults to OPENROUTER_API_KEY.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=None if profiled else 1.0,
        help="Model temperature. Default: 1.0",
    )
    parser.add_argument(
        "--num-predict",
        type=int,
        default=None if profiled else 4096,
        help="Maximum generated tokens. Default: 4096.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=None if profiled else 120.0,
        help="HTTP timeout in seconds. Default: 120",
    )
    parser.add_argument(
        "--openrouter-title",
        default=None if profiled else "recursive-research-agent",
        help="Optional X-Title header for OpenRouter rankings.",
    )
    parser.add_argument(
        "--openrouter-referer",
        help="Optional HTTP-Referer header for OpenRouter rankings.",
    )
    parser.add_argument(
        "--openrouter-provider",
        action="append",
        default=None if profiled else [],
        dest="openrouter_providers",
        help=(
            "OpenRouter provider slug to prefer, for example 'anthropic'. "
            "May be passed multiple times to set provider order."
        ),
    )
    parser.add_argument(
        "--openrouter-no-fallbacks",
        action="store_true",
        default=None if profiled else False,
        help="Disable fallback to other OpenRouter providers.",
    )
    parser.add_argument(
        "--openrouter-require-parameters",
        action="store_true",
        default=None if profiled else False,
        help=(
            "Only route to providers that support all request parameters, "
            "including structured JSON response_format."
        ),
    )
    parser.add_argument(
        "--openrouter-response-format",
        choices=["json_schema", "json_object", "none"],
        default=None if profiled else "json_schema",
        help=(
            "Structured response mode. json_schema is strict but needs provider "
            "support; json_object is looser and works with more providers; none "
            "uses prompt-only JSON instructions. Default: json_schema."
        ),
    )
    parser.add_argument(
        "--openrouter-max-transient-retries",
        type=int,
        default=None if profiled else 3,
        help="Retries for transient OpenRouter upstream failures. Default: 3.",
    )
    parser.add_argument(
        "--openrouter-retry-base-delay-seconds",
        type=float,
        default=None if profiled else 1.0,
        help="Base delay for OpenRouter retry backoff. Default: 1.0.",
    )


def _add_run_source_args(
    parser: argparse.ArgumentParser,
    *,
    profiled: bool = False,
) -> None:
    parser.add_argument(
        "--source-dir",
        help="Local directory of .md/.txt source files for deep-dives.",
    )
    parser.add_argument(
        "--web-search",
        choices=["brave", "tavily"],
        help="Optional web search provider for deep-dives.",
    )
    parser.add_argument(
        "--brave-api-key",
        help="Brave Search API key. Defaults to BRAVE_SEARCH_API_KEY.",
    )
    parser.add_argument(
        "--tavily-api-key",
        help="Tavily Search API key. Defaults to TAVILY_API_KEY.",
    )
    parser.add_argument(
        "--freshness-days",
        type=int,
        default=None if profiled else 730,
        help="Requested freshness window for web sources. Default: 730.",
    )
    parser.add_argument(
        "--search-results",
        type=int,
        default=None if profiled else 5,
        help="Maximum source results to provide per node. Default: 5.",
    )
    parser.add_argument(
        "--search-queries",
        type=int,
        default=None if profiled else 4,
        help="Maximum planned search queries to run per node. Default: 4.",
    )
    parser.add_argument(
        "--outputs-dir",
        default=None if profiled else str(DEFAULT_OUTPUTS_DIR),
        help=f"Run artifact output directory. Default: {DEFAULT_OUTPUTS_DIR}",
    )
    parser.add_argument("--max-depth", type=int, default=None if profiled else 1)
    parser.add_argument(
        "--max-total-nodes",
        type=int,
        default=None if profiled else 3,
    )


def _ollama_model_from_args(args: argparse.Namespace) -> OllamaModelClient:
    return OllamaModelClient(
        model_name=args.model,
        base_url=args.base_url,
        temperature=args.temperature,
        num_predict=args.num_predict,
        enable_thinking=args.think,
        keep_alive=args.keep_alive,
        timeout_seconds=args.timeout_seconds,
    )


def _openrouter_model_from_args(args: argparse.Namespace) -> OpenRouterModelClient:
    return OpenRouterModelClient(
        model_name=args.model,
        api_key=args.openrouter_api_key,
        base_url=args.base_url,
        temperature=args.temperature,
        max_tokens=args.num_predict,
        timeout_seconds=args.timeout_seconds,
        app_title=args.openrouter_title,
        http_referer=args.openrouter_referer,
        provider_order=args.openrouter_providers,
        allow_fallbacks=not args.openrouter_no_fallbacks,
        require_parameters=args.openrouter_require_parameters,
        response_format_mode=args.openrouter_response_format,
        max_transient_retries=args.openrouter_max_transient_retries,
        transient_retry_base_delay_seconds=args.openrouter_retry_base_delay_seconds,
    )


def _default_audit_path(run_id: str) -> Path:
    return DEFAULT_OUTPUTS_DIR / run_id / "audit.md"


def _default_dossier_path(run_id: str) -> Path:
    return DEFAULT_OUTPUTS_DIR / run_id / "dossier.md"


def _run_summary_row(
    conn: sqlite3.Connection,
    run_id: str,
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT run_id, company, parent_run_id, started_at, completed_at, status
        FROM runs
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()


def _run_node_status_counts(
    conn: sqlite3.Connection,
    run_id: str,
) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT status, COUNT(*) AS count
        FROM nodes
        WHERE run_id = ?
        GROUP BY status
        ORDER BY status ASC
        """,
        (run_id,),
    ).fetchall()
    return {row["status"]: int(row["count"]) for row in rows}


def _audit_progress_callback(
    outputs_dir: Path,
    *,
    verbose: bool = True,
):
    last_summary: list[str | None] = [None]

    def callback(conn: sqlite3.Connection, run_id: str) -> None:
        write_audit_markdown(
            conn,
            run_id=run_id,
            output_path=outputs_dir / run_id / "audit.md",
        )
        if not verbose:
            return
        summary = _run_progress_summary(conn, run_id)
        if summary != last_summary[0]:
            _log(f"[run {run_id}] {summary}")
            last_summary[0] = summary

    return callback


def _run_progress_summary(conn: sqlite3.Connection, run_id: str) -> str:
    run = db.get_run(conn, run_id)
    rows = conn.execute(
        """
        SELECT status, COUNT(*) AS count
        FROM nodes
        WHERE run_id = ?
        GROUP BY status
        ORDER BY status
        """,
        (run_id,),
    ).fetchall()
    counts = {row["status"]: int(row["count"]) for row in rows}
    total = sum(counts.values())
    parts = [
        f"status={run.status}",
        f"nodes={total}",
        f"pending={counts.get('pending', 0)}",
        f"waiting={counts.get('waiting_for_children', 0)}",
        f"complete={counts.get('complete', 0)}",
        f"failed={counts.get('failed', 0)}",
    ]
    return " ".join(parts)


def _log(message: str) -> None:
    print(f"[{_timestamp()}] {message}", flush=True)


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _model_call_metadata(output_json: str | None) -> dict[str, object]:
    if not output_json:
        return {}
    try:
        payload = json.loads(output_json)
    except json.JSONDecodeError:
        return {}
    metadata = payload.get("_model_response_metadata")
    return metadata if isinstance(metadata, dict) else {}


def _model_call_to_dict(call: db.ModelCallDetail) -> dict[str, object]:
    return {
        "call_id": call.call_id,
        "run_id": call.run_id,
        "node_id": call.node_id,
        "call_type": call.call_type,
        "model_name": call.model_name,
        "prompt_version": call.prompt_version,
        "input": _parse_json_value(call.input_json),
        "output_json": _parse_json_value(call.output_json),
        "output_text": call.output_text,
        "error": call.error,
        "started_at": call.started_at,
        "completed_at": call.completed_at,
    }


def _parse_json_value(value: str | None) -> object:
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _pretty_json_value(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, indent=2, sort_keys=True)


def _duration_ns(value: object) -> str:
    if not isinstance(value, int | float):
        return ""
    if value <= 0:
        return "0ms"
    milliseconds = value / 1_000_000
    if milliseconds < 1000:
        return f"{milliseconds:.0f}ms"
    return f"{milliseconds / 1000:.1f}s"


if __name__ == "__main__":
    raise SystemExit(main())
