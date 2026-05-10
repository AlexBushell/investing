import unittest

from app.prompts import (
    compact_deep_dive_retry_prompt,
    DEEP_DIVE_SYSTEM_PROMPT,
    deep_dive_prompt,
    REFLECT_SYSTEM_PROMPT,
    reflect_prompt,
    search_plan_prompt,
    SEARCH_PLAN_SYSTEM_PROMPT,
    scope_prompt,
)


class PromptTests(unittest.TestCase):
    def test_scope_prompt_forbids_priority_prefixes_in_topic(self):
        prompt = scope_prompt("Example Co")

        self.assertIn("Do not include priority labels", prompt)
        self.assertIn("Priority 1:", prompt)
        self.assertIn("priority` field", prompt)

    def test_deep_dive_prompt_requests_structured_fields(self):
        prompt = deep_dive_prompt(
            company="Example Co",
            topic="Revenue quality",
            investigation_brief="Investigate revenue quality.",
        )

        self.assertIn("`core_question`", prompt)
        self.assertIn("`key_findings`", prompt)
        self.assertIn("`evidence_gaps`", prompt)
        self.assertNotIn("END_OF_DEEP_DIVE_ANALYSIS", prompt)

    def test_search_plan_system_prompt_includes_query_examples(self):
        self.assertIn("Good query examples", SEARCH_PLAN_SYSTEM_PROMPT)
        self.assertIn("Bad query examples", SEARCH_PLAN_SYSTEM_PROMPT)
        self.assertIn("market share", SEARCH_PLAN_SYSTEM_PROMPT)
        self.assertIn("6 to 12", SEARCH_PLAN_SYSTEM_PROMPT)
        self.assertIn("Never copy the investigation brief", SEARCH_PLAN_SYSTEM_PROMPT)
        self.assertIn("Example output", SEARCH_PLAN_SYSTEM_PROMPT)
        self.assertIn("Prefer several narrow queries", SEARCH_PLAN_SYSTEM_PROMPT)
        self.assertIn("Return at most six queries", SEARCH_PLAN_SYSTEM_PROMPT)

    def test_deep_dive_system_prompt_includes_grounding_examples(self):
        self.assertIn("Example source-grounded claim", DEEP_DIVE_SYSTEM_PROMPT)
        self.assertIn("Example unsupported inference", DEEP_DIVE_SYSTEM_PROMPT)
        self.assertIn("Example evidence-gap language", DEEP_DIVE_SYSTEM_PROMPT)

    def test_search_plan_prompt_discourages_copying_brief_sentences(self):
        prompt = search_plan_prompt(
            company="Example Co",
            topic="Revenue quality",
            investigation_brief="Investigate revenue quality.",
        )

        self.assertIn("Do not copy sentences", prompt)
        self.assertIn("short keyword queries", prompt)

    def test_reflect_system_prompt_includes_child_thread_examples(self):
        self.assertIn("Example child thread to spawn", REFLECT_SYSTEM_PROMPT)
        self.assertIn("Example child thread not to spawn", REFLECT_SYSTEM_PROMPT)

    def test_reflect_prompt_discourages_child_for_every_gap(self):
        prompt = reflect_prompt("Analysis text.")

        self.assertIn("Do not create a child for every missing source", prompt)
        self.assertIn("Deep-dive analysis", prompt)

    def test_compact_deep_dive_retry_prompt_is_shorter_and_mentions_validation(self):
        prompt = compact_deep_dive_retry_prompt(
            original_prompt="Original task.",
            validation_error="Missing marker.",
        )

        self.assertIn("failed validation", prompt)
        self.assertIn("same JSON schema", prompt)
        self.assertNotIn("END_OF_DEEP_DIVE_ANALYSIS", prompt)
        self.assertIn("Good compact shape", prompt)
        self.assertIn("Bad unfinished shape", prompt)
        self.assertIn("completion sentinels", prompt)


if __name__ == "__main__":
    unittest.main()
