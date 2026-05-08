"""Model-call boundary and deterministic fake model client.

The worker should depend on the protocol in this module, not on Ollama or any
specific provider. Real model clients can be added later without changing the
orchestration contract.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections import defaultdict, deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, Field

from app.prompts import (
    DEEP_DIVE_SYSTEM_PROMPT,
    REFLECT_SYSTEM_PROMPT,
    SCOPE_SYSTEM_PROMPT,
    deep_dive_prompt,
    reflect_prompt,
    scope_prompt,
)
from app.search import SourceMaterial
from app.schemas import StrictBaseModel
from app.schemas import (
    ArbitrationDecision,
    CircularityArbitrationOutput,
    DeepDiveOutput,
    ExtractFindingsOutput,
    PersistentUncertaintyClassificationOutput,
    ReflectOutput,
    ScopeOutput,
)


TModel = TypeVar("TModel", bound=BaseModel)
JsonPayload = dict[str, Any]
JsonPoster = Callable[[str, JsonPayload, float], JsonPayload]


class OllamaError(RuntimeError):
    """Base exception for Ollama client failures."""


class OllamaStructuredOutputError(OllamaError):
    """Raised when Ollama returns a response that is not parseable JSON."""


class StructuredSmokeOutput(StrictBaseModel):
    """Tiny schema used to smoke-test Ollama structured output support."""

    company: str = Field(min_length=1)
    thread_topic: str = Field(min_length=1)
    priority: int = Field(ge=1, le=3)


@dataclass(frozen=True)
class AncestorContext:
    """Stable context from an ancestor node passed to a deep-dive call."""

    topic: str
    investigation_brief: str
    abstract: str


@dataclass(frozen=True)
class PriorFindingContext:
    """Retrieved prior finding context passed to a deep-dive call."""

    claim: str
    source: str
    claim_type: str
    source_type: str
    decay_class: str
    date_last_verified: str | None = None


@dataclass(frozen=True)
class PersistentUncertaintyContext:
    """Persistent uncertainty context passed to a deep-dive call."""

    description: str
    closure_class: str
    reasoning: str
    created_at: str | None = None


@dataclass(frozen=True)
class SourceMaterialContext:
    """Source material provided to a deep-dive call."""

    title: str
    url: str | None
    source_type: str
    published_at: str | None
    text: str

    @classmethod
    def from_source(cls, source: SourceMaterial) -> "SourceMaterialContext":
        return cls(
            title=source.title,
            url=source.url,
            source_type=source.source_type,
            published_at=source.published_at,
            text=source.text,
        )


@dataclass(frozen=True)
class DeepDiveContext:
    """Input envelope for a deep-dive call."""

    company: str
    topic: str
    investigation_brief: str
    ancestors: tuple[AncestorContext, ...] = ()
    source_materials: tuple[SourceMaterialContext, ...] = ()
    prior_findings: tuple[PriorFindingContext, ...] = ()
    persistent_uncertainties: tuple[PersistentUncertaintyContext, ...] = ()


@dataclass(frozen=True)
class ChildSummary:
    """Summary passed upward to branch synthesis."""

    topic: str
    summary: str
    failed: bool = False


@dataclass(frozen=True)
class BranchSynthesisContext:
    """Input envelope for a branch-synthesize call."""

    company: str
    topic: str
    analysis: str
    child_summaries: tuple[ChildSummary, ...] = ()


@dataclass(frozen=True)
class ModelCallRecord:
    """In-memory call record used by fake clients and tests."""

    call_type: str
    payload: dict[str, Any]


class ResearchModelClient(Protocol):
    """Protocol implemented by fake and real model clients."""

    def scope(self, company: str) -> ScopeOutput:
        """Produce initial root-level investigation briefs."""

    def deep_dive(self, context: DeepDiveContext) -> DeepDiveOutput:
        """Conduct a deep-dive investigation."""

    def reflect(self, analysis: str) -> ReflectOutput:
        """Identify child threads from an analysis."""

    def branch_synthesize(self, context: BranchSynthesisContext) -> str:
        """Synthesize a completed branch."""

    def extract_findings(self, analysis: str) -> ExtractFindingsOutput:
        """Extract atomic findings from an analysis."""

    def arbitrate_circularity(
        self,
        *,
        ancestor_brief: str,
        candidate_brief: str,
    ) -> CircularityArbitrationOutput:
        """Classify an ancestor/candidate similarity match."""

    def classify_persistent_uncertainty(
        self,
        *,
        description: str,
        why_unresolved: str | None,
    ) -> PersistentUncertaintyClassificationOutput:
        """Classify an unanswerable thread for persistent uncertainty storage."""


class OllamaGenerateClient:
    """Small `/api/generate` client for structured-output smoke tests."""

    def __init__(
        self,
        *,
        model_name: str = "gemma4:latest",
        base_url: str = "http://localhost:11434",
        temperature: float = 1.0,
        num_predict: int = 4096,
        enable_thinking: bool = False,
        timeout_seconds: float = 120.0,
        post_json: JsonPoster | None = None,
    ) -> None:
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.num_predict = num_predict
        self.enable_thinking = enable_thinking
        self.timeout_seconds = timeout_seconds
        self._post_json = post_json or _post_json

    def generate_structured(
        self,
        *,
        prompt: str,
        schema: type[TModel],
        system: str | None = None,
    ) -> TModel:
        """Generate and validate a structured response."""

        payload: JsonPayload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "format": schema.model_json_schema(),
            "options": {
                "temperature": self.temperature,
                "num_predict": self.num_predict,
            },
        }
        if system is not None:
            payload["system"] = _with_gemma_thinking_token(
                system,
                enable_thinking=self.enable_thinking,
            )
        if self.enable_thinking:
            payload["think"] = True

        response = self._post_json(
            f"{self.base_url}/api/generate",
            payload,
            self.timeout_seconds,
        )
        if response.get("done_reason") == "length":
            raise OllamaStructuredOutputError(
                "Ollama stopped because it reached the generation length limit. "
                "Increase num_predict or tighten the prompt."
            )

        raw_response = response.get("response")
        if not isinstance(raw_response, str):
            raise OllamaStructuredOutputError(
                "Ollama response did not contain a string 'response' field."
            )

        try:
            parsed = json.loads(raw_response)
        except json.JSONDecodeError as exc:
            raise OllamaStructuredOutputError(
                "Ollama structured response was not valid JSON."
            ) from exc

        return schema.model_validate(parsed)

    def smoke_structured_output(self, company: str = "Example Co") -> StructuredSmokeOutput:
        """Ask the model for a tiny structured research-thread object."""

        return self.generate_structured(
            system=(
                "You produce concise JSON that exactly matches the requested schema. "
                "Do not include markdown or commentary."
            ),
            prompt=(
                f"Return one initial research thread for {company}. "
                "The thread should be descriptive, not an investment recommendation."
            ),
            schema=StructuredSmokeOutput,
        )


class OllamaModelClient:
    """Ollama-backed implementation of the research model protocol.

    Only `scope` is implemented initially. The remaining call types are added
    one at a time so prompt behavior can be inspected safely.
    """

    def __init__(
        self,
        *,
        model_name: str = "gemma4:latest",
        base_url: str = "http://localhost:11434",
        temperature: float = 1.0,
        num_predict: int = 4096,
        enable_thinking: bool = False,
        timeout_seconds: float = 120.0,
        post_json: JsonPoster | None = None,
    ) -> None:
        self.generate_client = OllamaGenerateClient(
            model_name=model_name,
            base_url=base_url,
            temperature=temperature,
            num_predict=num_predict,
            enable_thinking=enable_thinking,
            timeout_seconds=timeout_seconds,
            post_json=post_json,
        )

    def scope(self, company: str) -> ScopeOutput:
        return self.generate_client.generate_structured(
            system=SCOPE_SYSTEM_PROMPT,
            prompt=scope_prompt(company),
            schema=ScopeOutput,
        )

    def deep_dive(self, context: DeepDiveContext) -> DeepDiveOutput:
        return self.generate_client.generate_structured(
            system=DEEP_DIVE_SYSTEM_PROMPT,
            prompt=deep_dive_prompt(
                company=context.company,
                topic=context.topic,
                investigation_brief=context.investigation_brief,
                ancestor_context=_format_ancestors(context.ancestors),
                source_material_context=_format_source_materials(
                    context.source_materials
                ),
                prior_findings_context=_format_prior_findings(
                    context.prior_findings
                ),
                persistent_uncertainties_context=_format_persistent_uncertainties(
                    context.persistent_uncertainties
                ),
            ),
            schema=DeepDiveOutput,
        )

    def reflect(self, analysis: str) -> ReflectOutput:
        return self.generate_client.generate_structured(
            system=REFLECT_SYSTEM_PROMPT,
            prompt=reflect_prompt(analysis),
            schema=ReflectOutput,
        )

    def branch_synthesize(self, context: BranchSynthesisContext) -> str:
        child_lines = "\n".join(
            f"- {child.topic}: {child.summary}" for child in context.child_summaries
        )
        return (
            f"Branch synthesis placeholder for {context.company}: {context.topic}.\n\n"
            f"Child summaries:\n{child_lines or 'No child summaries.'}"
        )

    def extract_findings(self, analysis: str) -> ExtractFindingsOutput:
        return ExtractFindingsOutput()

    def arbitrate_circularity(
        self,
        *,
        ancestor_brief: str,
        candidate_brief: str,
    ) -> CircularityArbitrationOutput:
        raise NotImplementedError(
            "Ollama arbitrate_circularity is not implemented yet."
        )

    def classify_persistent_uncertainty(
        self,
        *,
        description: str,
        why_unresolved: str | None,
    ) -> PersistentUncertaintyClassificationOutput:
        raise NotImplementedError(
            "Ollama classify_persistent_uncertainty is not implemented yet."
        )


class FakeModelClient:
    """Deterministic scriptable model client for worker tests.

    Scripted outputs are consumed FIFO per call type. If no scripted output is
    available, a valid conservative default is returned.
    """

    def __init__(
        self,
        *,
        scope_outputs: Iterable[ScopeOutput] = (),
        deep_dive_outputs: Iterable[DeepDiveOutput] = (),
        reflect_outputs: Iterable[ReflectOutput] = (),
        branch_syntheses: Iterable[str] = (),
        extract_findings_outputs: Iterable[ExtractFindingsOutput] = (),
        circularity_outputs: Iterable[CircularityArbitrationOutput] = (),
        uncertainty_outputs: Iterable[PersistentUncertaintyClassificationOutput] = (),
    ) -> None:
        self._scripts: dict[str, deque[Any]] = {
            "scope": deque(scope_outputs),
            "deep_dive": deque(deep_dive_outputs),
            "reflect": deque(reflect_outputs),
            "branch_synthesize": deque(branch_syntheses),
            "extract_findings": deque(extract_findings_outputs),
            "arbitrate_circularity": deque(circularity_outputs),
            "classify_persistent_uncertainty": deque(uncertainty_outputs),
        }
        self.calls: list[ModelCallRecord] = []

    def scope(self, company: str) -> ScopeOutput:
        self._record("scope", {"company": company})
        return self._next(
            "scope",
            ScopeOutput.model_validate(
                {
                    "root_threads": [
                        {
                            "topic": f"{company} business overview",
                            "description": (
                                f"Establish the basic operating picture for {company}."
                            ),
                            "priority": 1,
                            "investigation_brief": (
                                f"Investigate {company}'s business model, "
                                "reported operating structure, and major open "
                                "questions without making an investment judgement."
                            ),
                        }
                    ]
                }
            ),
        )

    def deep_dive(self, context: DeepDiveContext) -> DeepDiveOutput:
        self._record(
            "deep_dive",
            {
                "company": context.company,
                "topic": context.topic,
                "investigation_brief": context.investigation_brief,
                "ancestor_count": len(context.ancestors),
                "source_material_count": len(context.source_materials),
                "prior_finding_count": len(context.prior_findings),
                "persistent_uncertainty_count": len(context.persistent_uncertainties),
            },
        )
        return self._next(
            "deep_dive",
            DeepDiveOutput.model_validate(
                {
                    "analysis": (
                        f"Fake analysis for {context.company}: {context.topic}. "
                        "Per the fake source, this is deterministic test output. "
                        "END_OF_DEEP_DIVE_ANALYSIS."
                    ),
                    "abstract": (
                        f"{context.company} fake abstract for {context.topic}."
                    ),
                }
            ),
        )

    def reflect(self, analysis: str) -> ReflectOutput:
        self._record("reflect", {"analysis": analysis})
        return self._next("reflect", ReflectOutput())

    def branch_synthesize(self, context: BranchSynthesisContext) -> str:
        self._record(
            "branch_synthesize",
            {
                "company": context.company,
                "topic": context.topic,
                "analysis": context.analysis,
                "child_summary_count": len(context.child_summaries),
            },
        )
        return self._next(
            "branch_synthesize",
            f"Fake branch synthesis for {context.company}: {context.topic}.",
        )

    def extract_findings(self, analysis: str) -> ExtractFindingsOutput:
        self._record("extract_findings", {"analysis": analysis})
        return self._next("extract_findings", ExtractFindingsOutput())

    def arbitrate_circularity(
        self,
        *,
        ancestor_brief: str,
        candidate_brief: str,
    ) -> CircularityArbitrationOutput:
        self._record(
            "arbitrate_circularity",
            {
                "ancestor_brief": ancestor_brief,
                "candidate_brief": candidate_brief,
            },
        )
        return self._next(
            "arbitrate_circularity",
            CircularityArbitrationOutput(
                decision=ArbitrationDecision.GENUINELY_DISTINCT,
                reasoning="Fake default treats the candidate as distinct.",
            ),
        )

    def classify_persistent_uncertainty(
        self,
        *,
        description: str,
        why_unresolved: str | None,
    ) -> PersistentUncertaintyClassificationOutput:
        self._record(
            "classify_persistent_uncertainty",
            {
                "description": description,
                "why_unresolved": why_unresolved,
            },
        )
        return self._next(
            "classify_persistent_uncertainty",
            PersistentUncertaintyClassificationOutput(
                classification="unknowable",
                reasoning="Fake default classifies unanswerable threads as unknowable.",
            ),
        )

    def call_counts(self) -> dict[str, int]:
        """Return the number of calls by call type."""

        counts: defaultdict[str, int] = defaultdict(int)
        for call in self.calls:
            counts[call.call_type] += 1
        return dict(counts)

    def _next(self, call_type: str, default: Any) -> Any:
        if self._scripts[call_type]:
            return self._scripts[call_type].popleft()
        return default

    def _record(self, call_type: str, payload: dict[str, Any]) -> None:
        self.calls.append(ModelCallRecord(call_type=call_type, payload=payload))


def _format_ancestors(ancestors: tuple[AncestorContext, ...]) -> str:
    if not ancestors:
        return ""
    lines: list[str] = []
    for index, ancestor in enumerate(ancestors, start=1):
        lines.append(f"{index}. Topic: {ancestor.topic}")
        lines.append(f"   Brief: {ancestor.investigation_brief}")
        lines.append(f"   Abstract: {ancestor.abstract}")
    return "\n".join(lines)


def _format_source_materials(sources: tuple[SourceMaterialContext, ...]) -> str:
    if not sources:
        return ""
    lines: list[str] = []
    for index, source in enumerate(sources, start=1):
        lines.append(f"Source {index}: {source.title}")
        lines.append(f"Type: {source.source_type}")
        if source.url:
            lines.append(f"URL: {source.url}")
        if source.published_at:
            lines.append(f"Published at: {source.published_at}")
        lines.append("Text:")
        lines.append(source.text)
        lines.append("")
    return "\n".join(lines).strip()


def _format_prior_findings(findings: tuple[PriorFindingContext, ...]) -> str:
    if not findings:
        return ""
    lines: list[str] = []
    for index, finding in enumerate(findings, start=1):
        lines.append(f"{index}. Claim: {finding.claim}")
        lines.append(f"   Source: {finding.source}")
        lines.append(f"   Claim type: {finding.claim_type}")
        lines.append(f"   Source type: {finding.source_type}")
        lines.append(f"   Decay class: {finding.decay_class}")
        if finding.date_last_verified:
            lines.append(f"   Last verified: {finding.date_last_verified}")
    return "\n".join(lines)


def _format_persistent_uncertainties(
    uncertainties: tuple[PersistentUncertaintyContext, ...],
) -> str:
    if not uncertainties:
        return ""
    lines: list[str] = []
    for index, uncertainty in enumerate(uncertainties, start=1):
        lines.append(f"{index}. Description: {uncertainty.description}")
        lines.append(f"   Closure class: {uncertainty.closure_class}")
        lines.append(f"   Reasoning: {uncertainty.reasoning}")
        if uncertainty.created_at:
            lines.append(f"   Created at: {uncertainty.created_at}")
    return "\n".join(lines)


def _with_gemma_thinking_token(system: str, *, enable_thinking: bool) -> str:
    if not enable_thinking or system.startswith("<|think|>"):
        return system
    return f"<|think|>\n{system}"


def _post_json(url: str, payload: JsonPayload, timeout_seconds: float) -> JsonPayload:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        message = _ollama_error_message(error_body) or error_body or str(exc)
        raise OllamaError(
            f"Ollama returned HTTP {exc.code} from {url}: {message}"
        ) from exc
    except urllib.error.URLError as exc:
        raise OllamaError(f"Failed to call Ollama at {url}: {exc}") from exc

    try:
        decoded = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise OllamaError("Ollama returned invalid JSON.") from exc

    if not isinstance(decoded, dict):
        raise OllamaError("Ollama returned a non-object JSON response.")
    return decoded


def _ollama_error_message(error_body: str) -> str | None:
    try:
        decoded = json.loads(error_body)
    except json.JSONDecodeError:
        return None
    if not isinstance(decoded, dict):
        return None
    error = decoded.get("error")
    return error if isinstance(error, str) else None
