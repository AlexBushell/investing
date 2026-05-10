import unittest

from pydantic import ValidationError

from app.schemas import (
    ArbitrationDecision,
    CircularityArbitrationOutput,
    ClaimType,
    Confidence,
    DecayClass,
    DeepDiveOutput,
    DedupDecision,
    DeduplicationDecisionOutput,
    EvidenceBasis,
    ExtractFindingsOutput,
    ExtractedFinding,
    PersistentUncertaintyClassificationOutput,
    ReflectOutput,
    ResolutionState,
    SearchPlanOutput,
    SiblingConsolidationOutput,
    ScopeOutput,
    SourceType,
    ThreadCandidate,
)


class SchemaTests(unittest.TestCase):
    def test_scope_output_requires_at_least_one_root_thread(self):
        with self.assertRaises(ValidationError):
            ScopeOutput.model_validate({"root_threads": []})

    def test_scope_output_rejects_unexpected_fields(self):
        with self.assertRaises(ValidationError):
            ScopeOutput.model_validate(
                {
                    "root_threads": [
                        {
                            "topic": "Revenue quality",
                            "description": "Investigate reported revenue.",
                            "priority": 1,
                            "investigation_brief": "Study revenue quality.",
                            "extra": "not allowed",
                        }
                    ]
                }
            )

    def test_thread_candidate_recursion_gate(self):
        candidate = ThreadCandidate.model_validate(
            {
                "topic": "Customer concentration",
                "description": "Assess customer dependency.",
                "material": True,
                "priority": 1,
                "resolution_state": "unresolved_investigable",
                "evidence_basis": "direct",
                "investigation_brief": "Investigate customer concentration.",
            }
        )

        self.assertTrue(candidate.should_spawn_node)

    def test_thread_candidate_unanswerable_does_not_spawn_node(self):
        candidate = ThreadCandidate.model_validate(
            {
                "topic": "Private contract terms",
                "description": "Undisclosed contract economics.",
                "material": True,
                "priority": 1,
                "resolution_state": "unresolved_unanswerable",
                "evidence_basis": "inferred",
                "investigation_brief": "Try to determine private contract terms.",
            }
        )

        self.assertFalse(candidate.should_spawn_node)

    def test_speculative_thread_priority_is_demoted(self):
        candidate = ThreadCandidate.model_validate(
            {
                "topic": "Speculative supplier issue",
                "description": "Hypothetical supplier fragility.",
                "material": True,
                "priority": 1,
                "resolution_state": "unresolved_investigable",
                "evidence_basis": "speculative",
                "investigation_brief": "Investigate supplier fragility.",
            }
        )

        self.assertEqual(2, candidate.queue_priority)

    def test_speculative_thread_priority_demotion_caps_at_three(self):
        candidate = ThreadCandidate.model_validate(
            {
                "topic": "Speculative governance issue",
                "description": "Hypothetical governance weakness.",
                "material": True,
                "priority": 3,
                "resolution_state": "unresolved_investigable",
                "evidence_basis": "speculative",
                "investigation_brief": "Investigate governance weakness.",
            }
        )

        self.assertEqual(3, candidate.queue_priority)

    def test_deep_dive_output_accepts_empty_optional_lists(self):
        output = DeepDiveOutput.model_validate(
            {
                "core_question": "Assess Example Co revenue durability.",
                "source_assessment": "The supplied source is an annual report excerpt.",
                "key_findings": ["Source 1 states revenue increased."],
                "evidence_gaps": [],
                "conclusion": "The supplied source supports growth but not durability.",
                "abstract": "One paragraph abstract.",
            }
        )

        self.assertEqual([], output.contradictions)
        self.assertEqual([], output.discovered_threads)
        self.assertIn("## Evidence Gaps", output.analysis)

    def test_deep_dive_output_rejects_legacy_analysis_blob(self):
        with self.assertRaises(ValidationError):
            DeepDiveOutput.model_validate(
                {
                    "analysis": "Analysis that stops mid-sentence",
                    "abstract": "One paragraph abstract.",
                }
            )

    def test_deep_dive_output_rejects_completion_sentinel_in_fields(self):
        with self.assertRaises(ValidationError):
            DeepDiveOutput.model_validate(
                {
                    "core_question": "Assess Example Co revenue durability.",
                    "source_assessment": "The supplied source is an annual report excerpt.",
                    "key_findings": [
                        "Source 1 states revenue increased. END_OF_DEEP_DIVE_ANALYSIS."
                    ],
                    "evidence_gaps": [],
                    "conclusion": "The supplied source supports growth but not durability.",
                    "abstract": "One paragraph abstract.",
                }
            )

    def test_search_plan_accepts_up_to_six_queries(self):
        output = SearchPlanOutput.model_validate(
            {
                "queries": [
                    {
                        "query": f"Example Co source query {index}",
                        "purpose": "Find evidence.",
                    }
                    for index in range(6)
                ]
            }
        )

        self.assertEqual(6, len(output.queries))

    def test_search_plan_rejects_more_than_six_queries(self):
        with self.assertRaises(ValidationError):
            SearchPlanOutput.model_validate(
                {
                    "queries": [
                        {
                            "query": f"Example Co source query {index}",
                            "purpose": "Find evidence.",
                        }
                        for index in range(7)
                    ]
                }
            )

    def test_reflect_output_accepts_empty_children(self):
        output = ReflectOutput.model_validate({"child_threads": []})

        self.assertEqual([], output.child_threads)

    def test_sibling_consolidation_output_accepts_reasoning(self):
        output = SiblingConsolidationOutput.model_validate(
            {
                "child_threads": [],
                "reasoning": "The sibling set was already canonical.",
            }
        )

        self.assertEqual([], output.child_threads)
        self.assertEqual(
            "The sibling set was already canonical.",
            output.reasoning,
        )

    def test_extracted_finding_validates_enums(self):
        finding = ExtractedFinding.model_validate(
            {
                "claim": "Example Co reported revenue growth.",
                "claim_type": "observed_fact",
                "evidence": "Reported in the annual filing.",
                "source": "Example Co 2025 annual report",
                "source_type": "primary_filing",
                "primary_vs_secondary": True,
                "confidence": "high",
                "decay_class": "historical",
                "date_observed": "2026-05-08",
                "date_last_verified": "2026-05-08",
                "tags": ["revenue", ""],
            }
        )

        self.assertEqual(ClaimType.OBSERVED_FACT, finding.claim_type)
        self.assertEqual(SourceType.PRIMARY_FILING, finding.source_type)
        self.assertEqual(Confidence.HIGH, finding.confidence)
        self.assertEqual(DecayClass.HISTORICAL, finding.decay_class)
        self.assertEqual(["revenue"], finding.tags)

    def test_extract_findings_output_defaults_to_empty_list(self):
        output = ExtractFindingsOutput.model_validate({})

        self.assertEqual([], output.findings)

    def test_circularity_arbitration_output(self):
        output = CircularityArbitrationOutput.model_validate(
            {
                "decision": "same_question_rephrased",
                "reasoning": "The candidate repeats the ancestor question.",
            }
        )

        self.assertEqual(
            ArbitrationDecision.SAME_QUESTION_REPHRASED,
            output.decision,
        )

    def test_deduplication_decision_output(self):
        output = DeduplicationDecisionOutput.model_validate(
            {
                "decision": "reference_existing",
                "canonical_node_id": "node-123",
                "reasoning": "The candidate asks the same question as node-123.",
            }
        )

        self.assertEqual(DedupDecision.REFERENCE_EXISTING, output.decision)
        self.assertTrue(output.should_reference)

    def test_deduplication_decision_output_ignores_helper_fields(self):
        output = DeduplicationDecisionOutput.model_validate(
            {
                "decision": "distinct",
                "canonical_node_id": None,
                "reasoning": "No existing thread covers this candidate.",
                "distinct_with_null": None,
            }
        )

        self.assertEqual(DedupDecision.DISTINCT, output.decision)
        self.assertFalse(output.should_reference)

    def test_persistent_uncertainty_classification_maps_closure_class(self):
        output = PersistentUncertaintyClassificationOutput.model_validate(
            {
                "classification": "unknowable",
                "reasoning": "The relevant private contract is not disclosed.",
            }
        )

        self.assertEqual("unknowable", output.closure_class.value)

    def test_invalid_priority_is_rejected(self):
        with self.assertRaises(ValidationError):
            ThreadCandidate.model_validate(
                {
                    "topic": "Bad priority",
                    "description": "Priority is outside the allowed range.",
                    "material": True,
                    "priority": 4,
                    "resolution_state": "unresolved_investigable",
                    "evidence_basis": "direct",
                    "investigation_brief": "Investigate bad priority.",
                }
            )

    def test_invalid_resolution_state_is_rejected(self):
        with self.assertRaises(ValidationError):
            ThreadCandidate.model_validate(
                {
                    "topic": "Bad state",
                    "description": "Resolution state is invalid.",
                    "material": True,
                    "priority": 2,
                    "resolution_state": "maybe_later",
                    "evidence_basis": EvidenceBasis.DIRECT.value,
                    "investigation_brief": "Investigate invalid state.",
                }
            )

    def test_imported_resolution_state_enum_matches_expected_value(self):
        self.assertEqual(
            "resolved_within_analysis",
            ResolutionState.RESOLVED_WITHIN_ANALYSIS.value,
        )


if __name__ == "__main__":
    unittest.main()
