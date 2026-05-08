import unittest
import urllib.error
import urllib.request

from app.llm import (
    BranchSynthesisContext,
    ChildSummary,
    DeepDiveContext,
    FakeModelClient,
    OllamaGenerateClient,
    OllamaModelClient,
    SourceMaterialContext,
    OllamaStructuredOutputError,
    StructuredSmokeOutput,
)
from app.schemas import (
    ArbitrationDecision,
    CircularityArbitrationOutput,
    DeepDiveOutput,
    ReflectOutput,
    ScopeOutput,
)


class FakeModelClientTests(unittest.TestCase):
    def test_default_scope_output_is_valid_and_records_call(self):
        client = FakeModelClient()

        output = client.scope("Example Co")

        self.assertEqual(1, len(output.root_threads))
        self.assertEqual("Example Co", client.calls[0].payload["company"])
        self.assertEqual({"scope": 1}, client.call_counts())

    def test_scripted_outputs_are_consumed_fifo(self):
        first = ScopeOutput.model_validate(
            {
                "root_threads": [
                    {
                        "topic": "First",
                        "description": "First root.",
                        "priority": 1,
                        "investigation_brief": "First brief.",
                    }
                ]
            }
        )
        second = ScopeOutput.model_validate(
            {
                "root_threads": [
                    {
                        "topic": "Second",
                        "description": "Second root.",
                        "priority": 2,
                        "investigation_brief": "Second brief.",
                    }
                ]
            }
        )
        client = FakeModelClient(scope_outputs=[first, second])

        self.assertEqual("First", client.scope("Example Co").root_threads[0].topic)
        self.assertEqual("Second", client.scope("Example Co").root_threads[0].topic)

    def test_deep_dive_records_context_counts(self):
        client = FakeModelClient()

        output = client.deep_dive(
            DeepDiveContext(
                company="Example Co",
                topic="Revenue quality",
                investigation_brief="Investigate revenue quality.",
                source_materials=(
                    SourceMaterialContext(
                        title="Annual report excerpt",
                        url=None,
                        source_type="primary_filing",
                        published_at="2026-01-01",
                        text="Revenue grew 10%.",
                    ),
                ),
            )
        )

        self.assertIn("Revenue quality", output.analysis)
        self.assertEqual("deep_dive", client.calls[0].call_type)
        self.assertEqual(0, client.calls[0].payload["ancestor_count"])
        self.assertEqual(1, client.calls[0].payload["source_material_count"])
        self.assertEqual(0, client.calls[0].payload["prior_finding_count"])

    def test_scripted_deep_dive_output_is_returned(self):
        scripted = DeepDiveOutput.model_validate(
            {
                "analysis": "Scripted analysis. END_OF_DEEP_DIVE_ANALYSIS.",
                "abstract": "Scripted abstract.",
            }
        )
        client = FakeModelClient(deep_dive_outputs=[scripted])

        output = client.deep_dive(
            DeepDiveContext(
                company="Example Co",
                topic="Revenue quality",
                investigation_brief="Investigate revenue quality.",
            )
        )

        self.assertEqual(
            "Scripted analysis. END_OF_DEEP_DIVE_ANALYSIS.",
            output.analysis,
        )

    def test_reflect_defaults_to_no_children(self):
        client = FakeModelClient()

        output = client.reflect("Analysis text.")

        self.assertEqual(ReflectOutput(), output)
        self.assertEqual({"reflect": 1}, client.call_counts())

    def test_branch_synthesize_records_child_summary_count(self):
        client = FakeModelClient(branch_syntheses=["Scripted synthesis."])

        output = client.branch_synthesize(
            BranchSynthesisContext(
                company="Example Co",
                topic="Revenue quality",
                analysis="Analysis text.",
                child_summaries=(
                    ChildSummary(topic="Child", summary="Child summary."),
                ),
            )
        )

        self.assertEqual("Scripted synthesis.", output)
        self.assertEqual(1, client.calls[0].payload["child_summary_count"])

    def test_extract_findings_defaults_to_empty_findings(self):
        client = FakeModelClient()

        output = client.extract_findings("Analysis text.")

        self.assertEqual([], output.findings)
        self.assertEqual({"extract_findings": 1}, client.call_counts())

    def test_circularity_default_is_distinct(self):
        client = FakeModelClient()

        output = client.arbitrate_circularity(
            ancestor_brief="Investigate revenue.",
            candidate_brief="Investigate margins.",
        )

        self.assertEqual(ArbitrationDecision.GENUINELY_DISTINCT, output.decision)
        self.assertEqual(
            "Investigate revenue.",
            client.calls[0].payload["ancestor_brief"],
        )

    def test_scripted_circularity_output_is_returned(self):
        scripted = CircularityArbitrationOutput(
            decision=ArbitrationDecision.SAME_QUESTION_REPHRASED,
            reasoning="Same question.",
        )
        client = FakeModelClient(circularity_outputs=[scripted])

        output = client.arbitrate_circularity(
            ancestor_brief="Investigate revenue.",
            candidate_brief="Investigate revenue again.",
        )

        self.assertEqual(ArbitrationDecision.SAME_QUESTION_REPHRASED, output.decision)

    def test_uncertainty_default_is_unknowable(self):
        client = FakeModelClient()

        output = client.classify_persistent_uncertainty(
            description="Private contract terms.",
            why_unresolved="The contract is not public.",
        )

        self.assertEqual("unknowable", output.classification)
        self.assertEqual(
            "Private contract terms.",
            client.calls[0].payload["description"],
        )


class OllamaGenerateClientTests(unittest.TestCase):
    def test_generate_structured_posts_json_schema_and_validates_response(self):
        requests = []

        def fake_post(url, payload, timeout_seconds):
            requests.append((url, payload, timeout_seconds))
            return {
                "response": (
                    '{"company":"Example Co",'
                    '"thread_topic":"Business overview",'
                    '"priority":1}'
                )
            }

        client = OllamaGenerateClient(
            model_name="gemma4:latest",
            base_url="http://localhost:11434/",
            temperature=0.4,
            num_predict=1234,
            enable_thinking=True,
            timeout_seconds=7,
            post_json=fake_post,
        )

        output = client.generate_structured(
            prompt="Return JSON.",
            system="System prompt.",
            schema=StructuredSmokeOutput,
        )

        self.assertEqual("Example Co", output.company)
        self.assertEqual("Business overview", output.thread_topic)
        self.assertEqual(1, output.priority)

        url, payload, timeout_seconds = requests[0]
        self.assertEqual("http://localhost:11434/api/generate", url)
        self.assertEqual(7, timeout_seconds)
        self.assertEqual("gemma4:latest", payload["model"])
        self.assertEqual("Return JSON.", payload["prompt"])
        self.assertEqual("<|think|>\nSystem prompt.", payload["system"])
        self.assertTrue(payload["think"])
        self.assertFalse(payload["stream"])
        self.assertEqual(
            {"temperature": 0.4, "num_predict": 1234},
            payload["options"],
        )
        self.assertIn("properties", payload["format"])

    def test_generate_structured_rejects_length_stop(self):
        client = OllamaGenerateClient(
            post_json=lambda url, payload, timeout_seconds: {
                "response": (
                    '{"company":"Example Co",'
                    '"thread_topic":"Business overview",'
                    '"priority":1}'
                ),
                "done_reason": "length",
            }
        )

        with self.assertRaises(OllamaStructuredOutputError):
            client.generate_structured(
                prompt="Return JSON.",
                schema=StructuredSmokeOutput,
            )

    def test_generate_structured_without_thinking_does_not_add_think_fields(self):
        requests = []

        def fake_post(url, payload, timeout_seconds):
            requests.append(payload)
            return {
                "response": (
                    '{"company":"Example Co",'
                    '"thread_topic":"Business overview",'
                    '"priority":1}'
                )
            }

        client = OllamaGenerateClient(post_json=fake_post)

        client.generate_structured(
            prompt="Return JSON.",
            system="System prompt.",
            schema=StructuredSmokeOutput,
        )

        self.assertEqual("System prompt.", requests[0]["system"])
        self.assertNotIn("think", requests[0])

    def test_generate_structured_rejects_non_json_response_text(self):
        client = OllamaGenerateClient(
            post_json=lambda url, payload, timeout_seconds: {
                "response": "not json"
            }
        )

        with self.assertRaises(OllamaStructuredOutputError):
            client.generate_structured(
                prompt="Return JSON.",
                schema=StructuredSmokeOutput,
            )

    def test_generate_structured_rejects_missing_response_field(self):
        client = OllamaGenerateClient(
            post_json=lambda url, payload, timeout_seconds: {"done": True}
        )

        with self.assertRaises(OllamaStructuredOutputError):
            client.generate_structured(
                prompt="Return JSON.",
                schema=StructuredSmokeOutput,
            )

    def test_post_json_http_error_message_extracts_ollama_error_body(self):
        from app.llm import OllamaError, _post_json

        class FakeResponse:
            def read(self):
                return b'{"error":"model not found"}'

            def close(self):
                pass

        error = urllib.error.HTTPError(
            url="http://localhost:11434/api/generate",
            code=500,
            msg="Internal Server Error",
            hdrs={},
            fp=FakeResponse(),
        )

        def raise_http_error(request, timeout):
            raise error

        original_urlopen = urllib.request.urlopen
        urllib.request.urlopen = raise_http_error
        try:
            with self.assertRaises(OllamaError) as exc:
                _post_json(
                    "http://localhost:11434/api/generate",
                    {"model": "missing"},
                    1,
                )
        finally:
            urllib.request.urlopen = original_urlopen

        self.assertIn("HTTP 500", str(exc.exception))
        self.assertIn("model not found", str(exc.exception))


class OllamaModelClientTests(unittest.TestCase):
    def test_scope_uses_scope_schema_and_prompt(self):
        requests = []

        def fake_post(url, payload, timeout_seconds):
            requests.append(payload)
            return {
                "response": (
                    '{"root_threads":[{'
                    '"topic":"Revenue quality",'
                    '"description":"Investigate revenue durability.",'
                    '"priority":1,'
                    '"investigation_brief":"Investigate Example Co revenue quality."'
                    '}]}'
                )
            }

        client = OllamaModelClient(
            model_name="gemma4:latest",
            post_json=fake_post,
        )

        output = client.scope("Example Co")

        self.assertEqual("Revenue quality", output.root_threads[0].topic)
        request = requests[0]
        self.assertEqual("gemma4:latest", request["model"])
        self.assertIn("Example Co", request["prompt"])
        self.assertIn("scoping component", request["system"])
        self.assertIn("root_threads", request["format"]["properties"])

    def test_unimplemented_ollama_call_types_raise(self):
        client = OllamaModelClient()

        with self.assertRaises(NotImplementedError):
            client.arbitrate_circularity(
                ancestor_brief="Ancestor",
                candidate_brief="Candidate",
            )

    def test_ollama_extract_findings_placeholder_returns_empty_output(self):
        client = OllamaModelClient()

        output = client.extract_findings("Analysis.")

        self.assertEqual([], output.findings)

    def test_ollama_branch_synthesis_placeholder_uses_child_summaries(self):
        client = OllamaModelClient()

        output = client.branch_synthesize(
            BranchSynthesisContext(
                company="Example Co",
                topic="Revenue quality",
                analysis="Analysis.",
                child_summaries=(
                    ChildSummary(topic="Child", summary="Child summary."),
                ),
            )
        )

        self.assertIn("Branch synthesis placeholder", output)
        self.assertIn("Child summary", output)

    def test_deep_dive_uses_deep_dive_schema_and_prompt(self):
        requests = []

        def fake_post(url, payload, timeout_seconds):
            requests.append(payload)
            return {
                "response": (
                    '{"analysis":"Analysis states what evidence must be checked. '
                    'END_OF_DEEP_DIVE_ANALYSIS.",'
                    '"abstract":"Example Co abstract for revenue quality.",'
                    '"contradictions":[],'
                    '"discovered_threads":[]}'
                )
            }

        client = OllamaModelClient(post_json=fake_post)

        output = client.deep_dive(
            DeepDiveContext(
                company="Example Co",
                topic="Revenue quality",
                investigation_brief="Investigate Example Co revenue quality.",
                source_materials=(
                    SourceMaterialContext(
                        title="Annual report excerpt",
                        url="https://example.com/report",
                        source_type="primary_filing",
                        published_at="2026-01-01",
                        text="Example Co reported segment revenue.",
                    ),
                ),
            )
        )

        self.assertIn("evidence", output.analysis)
        request = requests[0]
        self.assertIn("deep-dive component", request["system"])
        self.assertIn("Revenue quality", request["prompt"])
        self.assertIn("Annual report excerpt", request["prompt"])
        self.assertIn("Example Co reported segment revenue.", request["prompt"])
        self.assertIn("analysis", request["format"]["properties"])
        self.assertIn("discovered_threads", request["format"]["properties"])

    def test_reflect_uses_reflect_schema_and_prompt(self):
        requests = []

        def fake_post(url, payload, timeout_seconds):
            requests.append(payload)
            return {
                "response": (
                    '{"child_threads":[{'
                    '"topic":"Customer concentration disclosure",'
                    '"description":"Investigate missing customer concentration disclosure.",'
                    '"material":true,'
                    '"priority":1,'
                    '"resolution_state":"unresolved_investigable",'
                    '"evidence_basis":"direct",'
                    '"investigation_brief":"Company: Example Co. Investigate customer concentration disclosures in public filings."'
                    '}]}'
                )
            }

        client = OllamaModelClient(post_json=fake_post)

        output = client.reflect("Example Co did not disclose customer concentration.")

        self.assertEqual(
            "Customer concentration disclosure",
            output.child_threads[0].topic,
        )
        request = requests[0]
        self.assertIn("reflection component", request["system"])
        self.assertIn("Deep-dive analysis", request["prompt"])
        self.assertIn("child_threads", request["format"]["properties"])


if __name__ == "__main__":
    unittest.main()
