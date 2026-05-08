import unittest

from app.prompts import deep_dive_prompt, reflect_prompt, scope_prompt


class PromptTests(unittest.TestCase):
    def test_scope_prompt_forbids_priority_prefixes_in_topic(self):
        prompt = scope_prompt("Example Co")

        self.assertIn("Do not include priority labels", prompt)
        self.assertIn("Priority 1:", prompt)
        self.assertIn("priority` field", prompt)

    def test_deep_dive_prompt_requires_evidence_gaps_heading(self):
        prompt = deep_dive_prompt(
            company="Example Co",
            topic="Revenue quality",
            investigation_brief="Investigate revenue quality.",
        )

        self.assertIn("## Evidence Gaps", prompt)
        self.assertIn("END_OF_DEEP_DIVE_ANALYSIS", prompt)

    def test_reflect_prompt_discourages_child_for_every_gap(self):
        prompt = reflect_prompt("Analysis text.")

        self.assertIn("Do not create a child for every missing source", prompt)
        self.assertIn("Deep-dive analysis", prompt)


if __name__ == "__main__":
    unittest.main()
