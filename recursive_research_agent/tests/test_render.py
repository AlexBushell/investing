import tempfile
import unittest
from pathlib import Path

from app import db
from app.llm import FakeModelClient
from app.orchestrator import run_to_completion, start_run
from app.render import (
    render_audit_markdown,
    render_dossier_markdown,
    write_audit_markdown,
    write_dossier_markdown,
)
from app.schemas import ReflectOutput


def child_thread(topic: str) -> dict:
    return {
        "topic": topic,
        "description": f"Description for {topic}.",
        "material": True,
        "priority": 1,
        "resolution_state": "unresolved_investigable",
        "evidence_basis": "direct",
        "triggering_text_span": "The analysis raised this issue.",
        "why_unresolved": "The analysis did not fully resolve it.",
        "investigation_brief": f"Investigate {topic}.",
    }


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_dir.name)
        self.conn = db.connect(self.base_path / "research.sqlite")
        db.initialize_database(self.conn)

    def tearDown(self):
        self.conn.close()
        self.temp_dir.cleanup()

    def test_audit_markdown_renders_tree_metadata_and_briefs(self):
        model = FakeModelClient(
            reflect_outputs=[
                ReflectOutput.model_validate(
                    {"child_threads": [child_thread("Margin durability")]}
                ),
                ReflectOutput.model_validate({"child_threads": []}),
            ],
            branch_syntheses=["Root synthesis."],
        )
        run = start_run(self.conn, company="Example Co", model=model)
        run_to_completion(self.conn, run_id=run.run_id, model=model)

        markdown = render_audit_markdown(self.conn, run.run_id)

        self.assertIn("# Brief Tree Audit: Example Co", markdown)
        self.assertIn("- **Example Co business overview** [`complete`]", markdown)
        self.assertIn("  - Priority: `1`", markdown)
        self.assertIn("  - Material: `true`", markdown)
        self.assertIn("  - Resolution: `unresolved_investigable`", markdown)
        self.assertIn("  - Evidence basis: `direct`", markdown)
        self.assertIn("  - Triggering span: The analysis raised this issue.", markdown)
        self.assertIn("  - **Margin durability** [`complete`]", markdown)
        self.assertIn("      Investigate Margin durability.", markdown)

    def test_dossier_markdown_renders_synthesis_analysis_and_children(self):
        model = FakeModelClient(
            reflect_outputs=[
                ReflectOutput.model_validate(
                    {"child_threads": [child_thread("Margin durability")]}
                ),
                ReflectOutput.model_validate({"child_threads": []}),
            ],
            branch_syntheses=["Root synthesis."],
        )
        run = start_run(self.conn, company="Example Co", model=model)
        run_to_completion(self.conn, run_id=run.run_id, model=model)

        markdown = render_dossier_markdown(self.conn, run.run_id)

        self.assertIn("# Recursive Research Dossier: Example Co", markdown)
        self.assertIn("## Example Co business overview", markdown)
        self.assertIn("Root synthesis.", markdown)
        self.assertIn("Fake analysis for Example Co", markdown)
        self.assertNotIn("END_OF_DEEP_DIVE_ANALYSIS", markdown)
        self.assertIn("### Margin durability", markdown)
        self.assertNotIn("Brief:", markdown)

    def test_renderers_handle_empty_run(self):
        run = db.create_run(self.conn, "Empty Co")

        audit = render_audit_markdown(self.conn, run.run_id)
        dossier = render_dossier_markdown(self.conn, run.run_id)

        self.assertIn("_No nodes yet._", audit)
        self.assertIn("_No investigations completed._", dossier)

    def test_write_markdown_helpers_create_parent_directories(self):
        run = db.create_run(self.conn, "Example Co")

        audit_path = write_audit_markdown(
            self.conn,
            run_id=run.run_id,
            output_path=self.base_path / "outputs" / "audit.md",
        )
        dossier_path = write_dossier_markdown(
            self.conn,
            run_id=run.run_id,
            output_path=self.base_path / "outputs" / "dossier.md",
        )

        self.assertTrue(audit_path.exists())
        self.assertTrue(dossier_path.exists())
        self.assertIn("Brief Tree Audit", audit_path.read_text(encoding="utf-8"))
        self.assertIn("Recursive Research Dossier", dossier_path.read_text(
            encoding="utf-8"
        ))


if __name__ == "__main__":
    unittest.main()
