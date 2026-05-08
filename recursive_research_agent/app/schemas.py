"""Structured model-call schemas.

These Pydantic models define the JSON contracts expected at the LLM boundary.
They do not perform orchestration; they validate and normalize model outputs so
the worker can make explicit decisions from typed data.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictBaseModel(BaseModel):
    """Base model that rejects unexpected model-output fields."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ResolutionState(str, Enum):
    UNRESOLVED_INVESTIGABLE = "unresolved_investigable"
    UNRESOLVED_UNANSWERABLE = "unresolved_unanswerable"
    RESOLVED_WITHIN_ANALYSIS = "resolved_within_analysis"


class EvidenceBasis(str, Enum):
    DIRECT = "direct"
    INFERRED = "inferred"
    SPECULATIVE = "speculative"


class ClaimType(str, Enum):
    OBSERVED_FACT = "observed_fact"
    MANAGEMENT_CLAIM = "management_claim"
    THIRD_PARTY_ALLEGATION = "third_party_allegation"
    INFERRED_CONCLUSION = "inferred_conclusion"
    STATISTICAL_OBSERVATION = "statistical_observation"
    HISTORICAL_EVENT = "historical_event"
    UNRESOLVED_CONTRADICTION = "unresolved_contradiction"


class SourceType(str, Enum):
    PRIMARY_FILING = "primary_filing"
    REGULATORY = "regulatory"
    REPUTABLE_JOURNALISM = "reputable_journalism"
    INDUSTRY_PUBLICATION = "industry_publication"
    MANAGEMENT_COMMUNICATION = "management_communication"
    AGGREGATOR = "aggregator"
    SOCIAL_MEDIA = "social_media"
    UNKNOWN = "unknown"


class Confidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DecayClass(str, Enum):
    HISTORICAL = "historical"
    STRUCTURAL = "structural"
    CURRENT = "current"


class ArbitrationDecision(str, Enum):
    NARROWER_SUBQUESTION = "narrower_subquestion"
    SAME_QUESTION_REPHRASED = "same_question_rephrased"
    GENUINELY_DISTINCT = "genuinely_distinct"


class ClosureClass(str, Enum):
    UNKNOWABLE = "unknowable"


class ScopeBrief(StrictBaseModel):
    topic: str = Field(min_length=1)
    description: str = Field(min_length=1)
    priority: int = Field(ge=1, le=3)
    investigation_brief: str = Field(min_length=1)


class ScopeOutput(StrictBaseModel):
    root_threads: list[ScopeBrief] = Field(min_length=1)


class ThreadCandidate(StrictBaseModel):
    topic: str = Field(min_length=1)
    description: str = Field(min_length=1)
    material: bool
    priority: int = Field(ge=1, le=3)
    resolution_state: ResolutionState
    evidence_basis: EvidenceBasis
    investigation_brief: str = Field(min_length=1)
    triggering_text_span: str | None = None
    why_unresolved: str | None = None

    @property
    def should_spawn_node(self) -> bool:
        """Return whether this candidate passes the recursion gates."""

        return (
            self.material
            and self.resolution_state == ResolutionState.UNRESOLVED_INVESTIGABLE
        )

    @property
    def queue_priority(self) -> int:
        """Return priority after speculative-thread demotion."""

        if self.evidence_basis != EvidenceBasis.SPECULATIVE:
            return self.priority
        return min(self.priority + 1, 3)


class SourceDescriptor(StrictBaseModel):
    source: str = Field(min_length=1)
    source_type: SourceType = SourceType.UNKNOWN
    primary_vs_secondary: bool
    date: str | None = None


class Contradiction(StrictBaseModel):
    topic: str = Field(min_length=1)
    description: str = Field(min_length=1)
    current_source: SourceDescriptor
    prior_source: SourceDescriptor
    why_contradictory: str = Field(min_length=1)


class DeepDiveOutput(StrictBaseModel):
    analysis: str = Field(min_length=1)
    abstract: str = Field(min_length=1)
    contradictions: list[Contradiction] = Field(default_factory=list)
    discovered_threads: list[ThreadCandidate] = Field(default_factory=list)

    @field_validator("analysis")
    @classmethod
    def require_completion_marker(cls, analysis: str) -> str:
        stripped = analysis.rstrip()
        if stripped.endswith("END_OF_DEEP_DIVE_ANALYSIS."):
            return stripped
        if stripped.endswith("END_OF_DEEP_DIVE_ANALYSIS"):
            return f"{stripped}."
        if stripped.endswith("END_OF_ANALYSIS."):
            return stripped.replace("END_OF_ANALYSIS.", "END_OF_DEEP_DIVE_ANALYSIS.")
        if stripped.endswith("END_OF_ANALYSIS"):
            return stripped.replace("END_OF_ANALYSIS", "END_OF_DEEP_DIVE_ANALYSIS.")
        if not stripped.endswith("END_OF_DEEP_DIVE_ANALYSIS."):
            raise ValueError(
                "deep-dive analysis must end with END_OF_DEEP_DIVE_ANALYSIS."
            )
        return stripped


class ReflectOutput(StrictBaseModel):
    child_threads: list[ThreadCandidate] = Field(default_factory=list)


class ExtractedFinding(StrictBaseModel):
    claim: str = Field(min_length=1)
    claim_type: ClaimType
    evidence: str = Field(min_length=1)
    source: str = Field(min_length=1)
    source_type: SourceType
    primary_vs_secondary: bool
    confidence: Confidence
    decay_class: DecayClass
    date_observed: str
    date_last_verified: str | None = None
    tags: list[str] = Field(default_factory=list)

    @field_validator("tags")
    @classmethod
    def reject_empty_tags(cls, tags: list[str]) -> list[str]:
        return [tag for tag in tags if tag]


class ExtractFindingsOutput(StrictBaseModel):
    findings: list[ExtractedFinding] = Field(default_factory=list)


class CircularityArbitrationOutput(StrictBaseModel):
    decision: ArbitrationDecision
    reasoning: str = Field(min_length=1)


class PersistentUncertaintyClassificationOutput(StrictBaseModel):
    classification: Literal["unknowable", "rejected_as_miscategorized"]
    reasoning: str = Field(min_length=1)

    @property
    def closure_class(self) -> ClosureClass | None:
        if self.classification == "unknowable":
            return ClosureClass.UNKNOWABLE
        return None
