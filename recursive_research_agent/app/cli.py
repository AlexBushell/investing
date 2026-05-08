"""Command line interface for the recursive research backend."""

from __future__ import annotations

import argparse
from pathlib import Path

from app import db
from app.llm import DeepDiveContext, SourceMaterialContext
from app.llm import FakeModelClient, OllamaGenerateClient, OllamaModelClient
from app.fsm import NodeEvent
from app.orchestrator import WorkerConfig, run_to_completion, start_run
from app.render import write_audit_markdown, write_dossier_markdown
from app.search import DirectorySearchProvider, source_from_file


DEFAULT_DB_PATH = Path("data") / "research.sqlite"
DEFAULT_OUTPUTS_DIR = Path("outputs") / "runs"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
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

    fake_run = subparsers.add_parser(
        "fake-run",
        help="Run the deterministic fake-model vertical slice.",
    )
    fake_run.add_argument("company", help="Company name.")
    fake_run.add_argument(
        "--outputs-dir",
        default=str(DEFAULT_OUTPUTS_DIR),
        help=f"Run artifact output directory. Default: {DEFAULT_OUTPUTS_DIR}",
    )
    fake_run.add_argument("--max-depth", type=int, default=8)
    fake_run.add_argument("--max-total-nodes", type=int, default=500)
    fake_run.add_argument(
        "--source-dir",
        help="Optional local directory of .md/.txt source files for deep-dives.",
    )
    fake_run.set_defaults(func=cmd_fake_run)

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
        help="Run a guarded real Ollama recursive pass using local source files.",
    )
    _add_ollama_args(ollama_run)
    ollama_run.add_argument("company", help="Company name.")
    ollama_run.add_argument(
        "--source-dir",
        required=True,
        help="Local directory of .md/.txt source files for deep-dives.",
    )
    ollama_run.add_argument(
        "--outputs-dir",
        default=str(DEFAULT_OUTPUTS_DIR),
        help=f"Run artifact output directory. Default: {DEFAULT_OUTPUTS_DIR}",
    )
    ollama_run.add_argument("--max-depth", type=int, default=1)
    ollama_run.add_argument("--max-total-nodes", type=int, default=3)
    ollama_run.set_defaults(func=cmd_ollama_run)

    return parser


def cmd_init_db(args: argparse.Namespace) -> int:
    conn = db.connect(args.db)
    try:
        db.initialize_database(conn)
    finally:
        conn.close()
    print(f"Initialized database: {args.db}")
    return 0


def cmd_fake_run(args: argparse.Namespace) -> int:
    conn = db.connect(args.db)
    try:
        db.initialize_database(conn)
        model = FakeModelClient()
        run = start_run(conn, company=args.company, model=model)
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
            ),
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

    print(f"Run complete: {completed.run_id}")
    print(f"Audit: {audit_path}")
    print(f"Dossier: {dossier_path}")
    return 0


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


def cmd_ollama_smoke(args: argparse.Namespace) -> int:
    client = OllamaGenerateClient(
        model_name=args.model,
        base_url=args.base_url,
        temperature=args.temperature,
        num_predict=args.num_predict,
        enable_thinking=args.think,
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
    conn = db.connect(args.db)
    try:
        db.initialize_database(conn)
        model = _ollama_model_from_args(args)
        run = start_run(
            conn,
            company=args.company,
            model=model,
            config=WorkerConfig(
                max_depth=args.max_depth,
                max_total_nodes=args.max_total_nodes,
                model_name=args.model,
                prompt_version="ollama-run-v1",
            ),
        )
        completed = run_to_completion(
            conn,
            run_id=run.run_id,
            model=model,
            search_provider=DirectorySearchProvider(args.source_dir),
            config=WorkerConfig(
                max_depth=args.max_depth,
                max_total_nodes=args.max_total_nodes,
                model_name=args.model,
                prompt_version="ollama-run-v1",
            ),
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

    print(f"Ollama run complete: {completed.run_id}")
    print(f"Status: {completed.status}")
    print(f"Audit: {audit_path}")
    print(f"Dossier: {dossier_path}")
    return 0


def _add_ollama_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--model",
        default="gemma4:latest",
        help="Ollama model name. Default: gemma4:latest",
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:11434",
        help="Ollama base URL. Default: http://localhost:11434",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=1.0,
        help="Model temperature. Default: 1.0",
    )
    parser.add_argument(
        "--num-predict",
        type=int,
        default=4096,
        help="Maximum generated tokens. Default: 4096",
    )
    parser.add_argument(
        "--think",
        action="store_true",
        help="Enable Ollama/Gemma thinking mode.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=120.0,
        help="HTTP timeout in seconds. Default: 120",
    )


def _ollama_model_from_args(args: argparse.Namespace) -> OllamaModelClient:
    return OllamaModelClient(
        model_name=args.model,
        base_url=args.base_url,
        temperature=args.temperature,
        num_predict=args.num_predict,
        enable_thinking=args.think,
        timeout_seconds=args.timeout_seconds,
    )


def _default_audit_path(run_id: str) -> Path:
    return DEFAULT_OUTPUTS_DIR / run_id / "audit.md"


def _default_dossier_path(run_id: str) -> Path:
    return DEFAULT_OUTPUTS_DIR / run_id / "dossier.md"


if __name__ == "__main__":
    raise SystemExit(main())
