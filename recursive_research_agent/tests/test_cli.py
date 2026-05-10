import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from app import db
from app.cli import build_parser, main
from app.fsm import NodeEvent
from app.llm import FakeModelClient
from app.orchestrator import start_run


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_dir.name)
        self.db_path = self.base_path / "research.sqlite"
        self.outputs_dir = self.base_path / "outputs"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_init_db_creates_database(self):
        output = self._run_cli("init-db")

        self.assertTrue(self.db_path.exists())
        self.assertIn("Initialized database", output)

        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute("SELECT version FROM schema_migrations").fetchone()
        finally:
            conn.close()
        self.assertEqual(1, row[0])

    def test_run_creates_artifacts(self):
        output = self._run_cli(
            "run",
            "Example Co",
            "--outputs-dir",
            str(self.outputs_dir),
        )

        self.assertIn("Run complete:", output)
        self.assertIn("[run ", output)
        self.assertIn("nodes=", output)
        self.assertIn("pending=", output)
        self.assertIn("complete=", output)
        run_id = _extract_value(output, "Run complete: ")
        audit_path = self.outputs_dir / run_id / "audit.md"
        dossier_path = self.outputs_dir / run_id / "dossier.md"

        self.assertTrue(audit_path.exists())
        self.assertTrue(dossier_path.exists())
        self.assertIn("Brief Tree Audit: Example Co", audit_path.read_text(
            encoding="utf-8"
        ))
        self.assertIn("Recursive Research Dossier: Example Co", dossier_path.read_text(
            encoding="utf-8"
        ))

    def test_run_parser_accepts_source_dir(self):
        parser = build_parser()

        args = parser.parse_args([
            "run",
            "Example Co",
            "--source-dir",
            "sources",
        ])

        self.assertEqual("sources", args.source_dir)

    def test_run_parser_accepts_max_seconds(self):
        parser = build_parser()

        args = parser.parse_args([
            "run",
            "Example Co",
            "--max-seconds",
            "12.5",
        ])

        self.assertEqual(12.5, args.max_seconds)

    def test_fake_run_alias_still_works(self):
        parser = build_parser()

        args = parser.parse_args([
            "fake-run",
            "Example Co",
            "--source-dir",
            "sources",
        ])

        self.assertEqual("sources", args.source_dir)

    def test_render_and_audit_commands_write_explicit_outputs(self):
        output = self._run_cli(
            "run",
            "Example Co",
            "--outputs-dir",
            str(self.outputs_dir),
        )
        run_id = _extract_value(output, "Run complete: ")

        dossier_output = self.base_path / "custom" / "dossier.md"
        audit_output = self.base_path / "custom" / "audit.md"

        self._run_cli("render", run_id, "--output", str(dossier_output))
        self._run_cli("audit", run_id, "--output", str(audit_output))

        self.assertTrue(dossier_output.exists())
        self.assertTrue(audit_output.exists())
        self.assertIn("Recursive Research Dossier", dossier_output.read_text(
            encoding="utf-8"
        ))
        self.assertIn("Brief Tree Audit", audit_output.read_text(encoding="utf-8"))

    def test_model_calls_command_summarizes_ollama_metadata(self):
        conn = db.connect(self.db_path)
        try:
            db.initialize_database(conn)
            run = db.create_run(conn, "Example Co")
            call_id = db.create_model_call(
                conn,
                run_id=run.run_id,
                node_id=None,
                call_type="scope",
                model_name="gemma4:latest",
                prompt_version="test",
                input_payload={"company": "Example Co"},
            )
            db.complete_model_call(
                conn,
                call_id=call_id,
                output_payload={
                    "root_threads": [],
                    "_model_response_metadata": {
                        "load_duration": 1_500_000_000,
                        "total_duration": 2_000_000_000,
                        "eval_count": 42,
                    },
                },
            )
        finally:
            conn.close()

        output = self._run_cli("model-calls", run.run_id)

        self.assertIn("Call ID | Call Type", output)
        self.assertIn(call_id, output)
        self.assertIn("scope", output)
        self.assertIn("1.5s", output)
        self.assertIn("2.0s", output)
        self.assertIn("42", output)

    def test_model_call_command_prints_call_payloads(self):
        call_id = self._create_completed_model_call()

        output = self._run_cli("model-call", call_id)

        self.assertIn(f"Call ID: {call_id}", output)
        self.assertIn("Call Type: scope", output)
        self.assertIn("Input JSON:", output)
        self.assertIn('"company": "Example Co"', output)
        self.assertIn("Output JSON:", output)
        self.assertIn('"root_threads": []', output)

    def test_model_call_command_raw_prints_json(self):
        call_id = self._create_completed_model_call()

        output = self._run_cli("model-call", call_id, "--raw")
        payload = json.loads(output)

        self.assertEqual(call_id, payload["call_id"])
        self.assertEqual("scope", payload["call_type"])
        self.assertEqual({"company": "Example Co"}, payload["input"])
        self.assertEqual([], payload["output_json"]["root_threads"])

    def test_resume_parser_accepts_run_id_and_source_dir(self):
        parser = build_parser()

        args = parser.parse_args([
            "resume",
            "run-123",
            "--source-dir",
            "sources",
        ])

        self.assertEqual("run-123", args.run_id)
        self.assertEqual("sources", args.source_dir)

    def test_resume_parser_accepts_max_seconds(self):
        parser = build_parser()

        args = parser.parse_args([
            "resume",
            "run-123",
            "--max-seconds",
            "5",
        ])

        self.assertEqual(5.0, args.max_seconds)

    def test_resume_completes_interrupted_run_and_writes_artifacts(self):
        conn = db.connect(self.db_path)
        try:
            db.initialize_database(conn)
            run = start_run(conn, company="Example Co", model=FakeModelClient())
            root = db.root_nodes(conn, run.run_id)[0]
            db.apply_node_event(
                conn,
                node_id=root.node_id,
                event=NodeEvent.START_INVESTIGATION,
            )
        finally:
            conn.close()

        output = self._run_cli(
            "resume",
            run.run_id,
            "--outputs-dir",
            str(self.outputs_dir),
        )

        self.assertIn("Run complete:", output)
        audit_path = self.outputs_dir / run.run_id / "audit.md"
        dossier_path = self.outputs_dir / run.run_id / "dossier.md"
        self.assertTrue(audit_path.exists())
        self.assertTrue(dossier_path.exists())
        self.assertIn("`complete`", audit_path.read_text(encoding="utf-8"))

    def test_run_with_zero_second_budget_pauses_and_writes_artifacts(self):
        output = self._run_cli(
            "run",
            "Example Co",
            "--outputs-dir",
            str(self.outputs_dir),
            "--max-seconds",
            "0",
        )

        self.assertIn("Run paused:", output)
        self.assertIn("Status: running", output)
        run_id = _extract_value(output, "Run paused: ")
        audit_path = self.outputs_dir / run_id / "audit.md"
        dossier_path = self.outputs_dir / run_id / "dossier.md"
        self.assertTrue(audit_path.exists())
        self.assertTrue(dossier_path.exists())

    def test_ollama_smoke_parser_defaults(self):
        parser = build_parser()

        args = parser.parse_args(["ollama-smoke"])

        self.assertEqual("gemma4:latest", args.model)
        self.assertEqual("http://localhost:11434", args.base_url)
        self.assertEqual(1.0, args.temperature)
        self.assertEqual(4096, args.num_predict)
        self.assertFalse(args.think)
        self.assertEqual("5m", args.keep_alive)
        self.assertEqual("Example Co", args.company)

    def test_ollama_scope_parser_accepts_company_and_model(self):
        parser = build_parser()

        args = parser.parse_args([
            "ollama-scope",
            "--model",
            "gemma4:latest",
            "Example Co",
        ])

        self.assertEqual("gemma4:latest", args.model)
        self.assertEqual("Example Co", args.company)

    def test_ollama_scope_parser_accepts_thinking_flag(self):
        parser = build_parser()

        args = parser.parse_args(["ollama-scope", "--think", "Example Co"])

        self.assertTrue(args.think)

    def test_ollama_scope_parser_accepts_keep_alive(self):
        parser = build_parser()

        args = parser.parse_args([
            "ollama-scope",
            "--keep-alive",
            "30m",
            "Example Co",
        ])

        self.assertEqual("30m", args.keep_alive)

    def test_ollama_scope_run_parser_defaults_outputs_dir(self):
        parser = build_parser()

        args = parser.parse_args(["ollama-scope-run", "Example Co"])

        self.assertEqual("Example Co", args.company)
        self.assertEqual("outputs/runs", args.outputs_dir.replace("\\", "/"))

    def test_ollama_deep_dive_smoke_parser_defaults_outputs_dir(self):
        parser = build_parser()

        args = parser.parse_args(["ollama-deep-dive-smoke", "Example Co"])

        self.assertEqual("Example Co", args.company)
        self.assertEqual("outputs/runs", args.outputs_dir.replace("\\", "/"))
        self.assertEqual([], args.source_file)

    def test_ollama_deep_dive_smoke_parser_accepts_source_files(self):
        parser = build_parser()

        args = parser.parse_args([
            "ollama-deep-dive-smoke",
            "Example Co",
            "--source-file",
            "one.md",
            "--source-file",
            "two.md",
        ])

        self.assertEqual(["one.md", "two.md"], args.source_file)

    def test_ollama_reflect_smoke_parser_accepts_source_files(self):
        parser = build_parser()

        args = parser.parse_args([
            "ollama-reflect-smoke",
            "Example Co",
            "--source-file",
            "source.md",
        ])

        self.assertEqual("Example Co", args.company)
        self.assertEqual(["source.md"], args.source_file)

    def test_ollama_run_parser_accepts_source_dir(self):
        parser = build_parser()

        args = parser.parse_args([
            "ollama-run",
            "Example Co",
            "--source-dir",
            "sources",
        ])

        self.assertEqual("Example Co", args.company)
        self.assertEqual("sources", args.source_dir)
        self.assertEqual(1, args.max_depth)
        self.assertEqual(3, args.max_total_nodes)
        self.assertEqual(4, args.search_queries)

    def test_ollama_run_parser_accepts_brave_web_search(self):
        parser = build_parser()

        args = parser.parse_args([
            "ollama-run",
            "Example Co",
            "--web-search",
            "brave",
            "--brave-api-key",
            "test-key",
            "--freshness-days",
            "365",
            "--search-results",
            "2",
            "--search-queries",
            "2",
        ])

        self.assertEqual("brave", args.web_search)
        self.assertEqual("test-key", args.brave_api_key)
        self.assertEqual(365, args.freshness_days)
        self.assertEqual(2, args.search_results)
        self.assertEqual(2, args.search_queries)

    def test_ollama_run_parser_accepts_tavily_web_search(self):
        parser = build_parser()

        args = parser.parse_args([
            "ollama-run",
            "Example Co",
            "--web-search",
            "tavily",
            "--tavily-api-key",
            "tvly-key",
            "--freshness-days",
            "30",
        ])

        self.assertEqual("tavily", args.web_search)
        self.assertEqual("tvly-key", args.tavily_api_key)
        self.assertEqual(30, args.freshness_days)

    def test_ollama_run_with_brave_requires_api_key(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(SystemExit):
                self._run_cli(
                    "ollama-run",
                    "Example Co",
                    "--web-search",
                    "brave",
                )

    def test_ollama_run_with_tavily_requires_api_key(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(SystemExit):
                self._run_cli(
                    "ollama-run",
                    "Example Co",
                    "--web-search",
                    "tavily",
                )

    def test_openrouter_run_parser_accepts_model_and_brave_web_search(self):
        parser = build_parser()

        args = parser.parse_args([
            "openrouter-run",
            "Example Co",
            "--model",
            "openai/gpt-4.1",
            "--openrouter-api-key",
            "router-key",
            "--web-search",
            "brave",
            "--brave-api-key",
            "brave-key",
            "--search-results",
            "6",
            "--search-queries",
            "3",
            "--max-depth",
            "2",
            "--max-total-nodes",
            "4",
            "--openrouter-provider",
            "anthropic",
            "--openrouter-no-fallbacks",
            "--openrouter-require-parameters",
            "--openrouter-response-format",
            "json_object",
        ])

        self.assertEqual("Example Co", args.company)
        self.assertEqual("openai/gpt-4.1", args.model)
        self.assertEqual("router-key", args.openrouter_api_key)
        self.assertEqual("brave", args.web_search)
        self.assertEqual("brave-key", args.brave_api_key)
        self.assertEqual(6, args.search_results)
        self.assertEqual(3, args.search_queries)
        self.assertEqual(2, args.max_depth)
        self.assertEqual(4, args.max_total_nodes)
        self.assertEqual(["anthropic"], args.openrouter_providers)
        self.assertTrue(args.openrouter_no_fallbacks)
        self.assertTrue(args.openrouter_require_parameters)
        self.assertEqual("json_object", args.openrouter_response_format)

    def test_openrouter_run_parser_accepts_model_and_tavily_web_search(self):
        parser = build_parser()

        args = parser.parse_args([
            "openrouter-run",
            "Example Co",
            "--model",
            "openai/gpt-4.1",
            "--openrouter-api-key",
            "router-key",
            "--web-search",
            "tavily",
            "--tavily-api-key",
            "tvly-key",
        ])

        self.assertEqual("tavily", args.web_search)
        self.assertEqual("tvly-key", args.tavily_api_key)

    def test_openrouter_run_requires_openrouter_api_key(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(SystemExit):
                self._run_cli(
                    "openrouter-run",
                    "Example Co",
                    "--model",
                    "openai/gpt-4.1",
                    "--source-dir",
                    "sources",
                )

    def _run_cli(self, *args: str) -> str:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            exit_code = main(["--db", str(self.db_path), *args])
        self.assertEqual(0, exit_code)
        return stdout.getvalue()

    def _create_completed_model_call(self) -> str:
        conn = db.connect(self.db_path)
        try:
            db.initialize_database(conn)
            run = db.create_run(conn, "Example Co")
            call_id = db.create_model_call(
                conn,
                run_id=run.run_id,
                node_id=None,
                call_type="scope",
                model_name="gemma4:latest",
                prompt_version="test",
                input_payload={"company": "Example Co"},
            )
            db.complete_model_call(
                conn,
                call_id=call_id,
                output_payload={"root_threads": []},
                output_text="raw response text",
            )
            return call_id
        finally:
            conn.close()


def _extract_value(output: str, prefix: str) -> str:
    for line in output.splitlines():
        if line.startswith(prefix):
            return line.removeprefix(prefix).strip()
    raise AssertionError(f"Missing line starting with {prefix!r}: {output}")


if __name__ == "__main__":
    unittest.main()
