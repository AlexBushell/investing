import io
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from app.cli import build_parser, main


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

    def test_fake_run_creates_artifacts(self):
        output = self._run_cli(
            "fake-run",
            "Example Co",
            "--outputs-dir",
            str(self.outputs_dir),
        )

        self.assertIn("Run complete:", output)
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

    def test_fake_run_parser_accepts_source_dir(self):
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
            "fake-run",
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

    def test_ollama_smoke_parser_defaults(self):
        parser = build_parser()

        args = parser.parse_args(["ollama-smoke"])

        self.assertEqual("gemma4:latest", args.model)
        self.assertEqual("http://localhost:11434", args.base_url)
        self.assertEqual(1.0, args.temperature)
        self.assertEqual(4096, args.num_predict)
        self.assertFalse(args.think)
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

    def test_ollama_run_parser_requires_and_accepts_source_dir(self):
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

    def _run_cli(self, *args: str) -> str:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            exit_code = main(["--db", str(self.db_path), *args])
        self.assertEqual(0, exit_code)
        return stdout.getvalue()


def _extract_value(output: str, prefix: str) -> str:
    for line in output.splitlines():
        if line.startswith(prefix):
            return line.removeprefix(prefix).strip()
    raise AssertionError(f"Missing line starting with {prefix!r}: {output}")


if __name__ == "__main__":
    unittest.main()
