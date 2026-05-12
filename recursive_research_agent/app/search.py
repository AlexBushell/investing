"""Search and source-material boundary.

The orchestration layer should depend on this module's small abstractions, not
on a specific web/search provider. Real providers can later adapt API responses
into `SourceMaterial` records.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


JsonObject = dict[str, object]
JsonRequest = dict[str, object]
MAX_PROVIDER_TEXT_CHARS = 4000


@dataclass(frozen=True)
class SourceMaterial:
    title: str
    url: str | None
    source_type: str
    published_at: str | None
    text: str
    retrieved_at: str | None = None
    source_date_basis: str | None = None
    staleness_note: str | None = None


class SearchProvider(Protocol):
    def search(self, *, company: str, query: str, max_results: int = 5) -> list[SourceMaterial]:
        """Return source materials relevant to a company/query pair."""


class FakeSearchProvider:
    """Deterministic provider for tests and local smoke runs."""

    def __init__(self, sources: list[SourceMaterial] | None = None) -> None:
        self.sources = sources or []
        self.calls: list[dict[str, object]] = []

    def search(self, *, company: str, query: str, max_results: int = 5) -> list[SourceMaterial]:
        self.calls.append(
            {
                "company": company,
                "query": query,
                "max_results": max_results,
            }
        )
        return self.sources[:max_results]


class SearchProviderError(RuntimeError):
    """Raised when an external search provider cannot return usable results."""


class CompositeSearchProvider:
    """Combine multiple providers behind the `SearchProvider` protocol."""

    def __init__(self, providers: list[SearchProvider]) -> None:
        self.providers = providers

    def search(self, *, company: str, query: str, max_results: int = 5) -> list[SourceMaterial]:
        provider_results: list[list[SourceMaterial]] = []
        for provider in self.providers:
            provider_results.append(
                provider.search(
                    company=company,
                    query=query,
                    max_results=max_results,
                )
            )

        results: list[SourceMaterial] = []
        for index in range(max_results):
            for sources in provider_results:
                if index < len(sources):
                    results.append(sources[index])
                    if len(results) >= max_results:
                        return results
        return results


class BraveSearchProvider:
    """Brave Search API provider that returns result snippets as source material."""

    MAX_QUERY_LENGTH = 400

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = "https://api.search.brave.com/res/v1/web/search",
        country: str = "us",
        search_lang: str = "en",
        freshness_days: int | None = None,
        timeout_seconds: float = 30.0,
        clock: Callable[[], datetime] | None = None,
        get_json: Callable[
            [str, dict[str, str], dict[str, str], float],
            JsonObject,
        ] | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get(
            "BRAVE_SEARCH_API_KEY"
        )
        self.base_url = base_url
        self.country = country
        self.search_lang = search_lang
        self.freshness_days = freshness_days
        self.timeout_seconds = timeout_seconds
        self.clock = clock or (lambda: datetime.now(UTC))
        self.get_json = get_json or _get_json

    def search(self, *, company: str, query: str, max_results: int = 5) -> list[SourceMaterial]:
        if not self.api_key:
            raise SearchProviderError(
                "BRAVE_SEARCH_API_KEY is required for Brave Search."
            )

        payload = self.get_json(
            self.base_url,
            {
                "X-Subscription-Token": self.api_key,
                "Accept": "application/json",
            },
            {
                "q": _compact_search_query(
                    company=company,
                    query=query,
                    max_length=self.MAX_QUERY_LENGTH,
                ),
                "count": str(max_results),
                "country": self.country,
                "search_lang": self.search_lang,
            },
            self.timeout_seconds,
        )
        results = _brave_web_results(payload)
        retrieved_at = _format_datetime(self.clock())
        return [
            _source_from_brave_result(
                result,
                retrieved_at=retrieved_at,
                freshness_days=self.freshness_days,
            )
            for result in results[:max_results]
        ]


class TavilySearchProvider:
    """Tavily Search API provider that returns result snippets as source material."""

    MAX_QUERY_LENGTH = 400

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = "https://api.tavily.com/search",
        topic: str = "general",
        search_depth: str = "advanced",
        include_raw_content: str | bool = False,
        freshness_days: int | None = None,
        timeout_seconds: float = 30.0,
        clock: Callable[[], datetime] | None = None,
        post_json: Callable[
            [str, dict[str, str], JsonRequest, float],
            JsonObject,
        ] | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get(
            "TAVILY_API_KEY"
        )
        self.base_url = base_url
        self.topic = topic
        self.search_depth = search_depth
        self.include_raw_content = include_raw_content
        self.freshness_days = freshness_days
        self.timeout_seconds = timeout_seconds
        self.clock = clock or (lambda: datetime.now(UTC))
        self.post_json = post_json or _post_json_request

    def search(self, *, company: str, query: str, max_results: int = 5) -> list[SourceMaterial]:
        if not self.api_key:
            raise SearchProviderError(
                "TAVILY_API_KEY is required for Tavily Search."
            )

        payload: JsonRequest = {
            "query": _compact_search_query(
                company=company,
                query=query,
                max_length=self.MAX_QUERY_LENGTH,
            ),
            "topic": self.topic,
            "search_depth": self.search_depth,
            "max_results": max_results,
            "include_raw_content": self.include_raw_content,
            "include_answer": False,
            "include_images": False,
            "include_favicon": False,
        }
        if self.freshness_days is not None:
            payload["time_range"] = _tavily_time_range(self.freshness_days)

        response = self.post_json(
            self.base_url,
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            payload,
            self.timeout_seconds,
        )
        results = _tavily_results(response)
        retrieved_at = _format_datetime(self.clock())
        return [
            _source_from_tavily_result(
                result,
                retrieved_at=retrieved_at,
                freshness_days=self.freshness_days,
            )
            for result in results[:max_results]
        ]


class DirectorySearchProvider:
    """Load local markdown/text files and rank them by simple lexical overlap."""

    def __init__(
        self,
        source_dir: str | Path,
        *,
        chunk_size_chars: int = 2400,
        chunk_overlap_chars: int = 300,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.source_dir = Path(source_dir)
        self.chunk_size_chars = chunk_size_chars
        self.chunk_overlap_chars = chunk_overlap_chars
        self.clock = clock or (lambda: datetime.now(UTC))

    def search(self, *, company: str, query: str, max_results: int = 5) -> list[SourceMaterial]:
        sources = self._source_chunks()
        scored = [
            (_score_source(source, company=company, query=query), source)
            for source in sources
        ]
        ranked = [
            source
            for score, source in sorted(
                scored,
                key=lambda item: (-item[0], item[1].title.lower()),
            )
            if score > 0
        ]
        return ranked[:max_results]

    def _source_files(self) -> list[Path]:
        if not self.source_dir.exists():
            return []
        return [
            path
            for path in self.source_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in {".md", ".txt"}
        ]

    def _source_chunks(self) -> list[SourceMaterial]:
        chunks: list[SourceMaterial] = []
        for path in self._source_files():
            source = source_from_file(path, retrieved_at=_format_datetime(self.clock()))
            text_chunks = chunk_text(
                source.text,
                chunk_size_chars=self.chunk_size_chars,
                chunk_overlap_chars=self.chunk_overlap_chars,
            )
            if len(text_chunks) == 1:
                chunks.append(source)
                continue

            for index, text in enumerate(text_chunks, start=1):
                chunks.append(
                    SourceMaterial(
                        title=f"{source.title}#chunk-{index}",
                        url=source.url,
                        source_type=source.source_type,
                        published_at=source.published_at,
                        text=text,
                        retrieved_at=source.retrieved_at,
                        source_date_basis=source.source_date_basis,
                        staleness_note=source.staleness_note,
                    )
                )
        return chunks


def source_from_file(
    path: str | Path,
    *,
    source_type: str = "user_supplied",
    published_at: str | None = None,
    retrieved_at: str | None = None,
    source_date_basis: str | None = None,
    staleness_note: str | None = None,
) -> SourceMaterial:
    """Load a local text/markdown file as source material."""

    source_path = Path(path)
    return SourceMaterial(
        title=source_path.name,
        url=None,
        source_type=source_type,
        published_at=published_at,
        text=source_path.read_text(encoding="utf-8"),
        retrieved_at=retrieved_at,
        source_date_basis=source_date_basis,
        staleness_note=staleness_note,
    )


def _score_source(source: SourceMaterial, *, company: str, query: str) -> int:
    haystack = " ".join([source.title, source.text]).lower()
    terms = _terms(f"{company} {query}")
    return sum(1 for term in terms if term in haystack)


def chunk_text(
    text: str,
    *,
    chunk_size_chars: int,
    chunk_overlap_chars: int,
) -> list[str]:
    """Split text into stable overlapping chunks."""

    stripped = text.strip()
    if not stripped:
        return []
    if chunk_size_chars <= 0:
        raise ValueError("chunk_size_chars must be positive")
    if chunk_overlap_chars < 0:
        raise ValueError("chunk_overlap_chars must not be negative")
    if chunk_size_chars <= chunk_overlap_chars:
        raise ValueError("chunk_size_chars must be greater than chunk_overlap_chars")
    if len(stripped) <= chunk_size_chars:
        return [stripped]

    chunks: list[str] = []
    start = 0
    while start < len(stripped):
        end = min(start + chunk_size_chars, len(stripped))
        if end < len(stripped):
            boundary = _chunk_boundary(stripped, start=start, end=end)
            if boundary > start:
                end = boundary
        chunk = stripped[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(stripped):
            break
        next_start = end - chunk_overlap_chars
        start = next_start if next_start > start else end
    return chunks


def _chunk_boundary(text: str, *, start: int, end: int) -> int:
    minimum_boundary = start + max(1, (end - start) // 2)
    paragraph = text.rfind("\n\n", start, end)
    if paragraph >= minimum_boundary:
        return paragraph
    sentence = max(
        text.rfind(". ", start, end),
        text.rfind("? ", start, end),
        text.rfind("! ", start, end),
    )
    if sentence >= minimum_boundary:
        return sentence + 1
    return end


def _format_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _get_json(
    url: str,
    headers: dict[str, str],
    params: dict[str, str],
    timeout_seconds: float,
) -> JsonObject:
    request_url = f"{url}?{urlencode(params)}"
    request = Request(request_url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise SearchProviderError(
            f"Brave Search returned HTTP {exc.code}: {message}"
        ) from exc
    except (URLError, TimeoutError) as exc:
        raise SearchProviderError(f"Failed to call Brave Search: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SearchProviderError("Brave Search returned invalid JSON.") from exc


def _post_json_request(
    url: str,
    headers: dict[str, str],
    payload: JsonRequest,
    timeout_seconds: float,
) -> JsonObject:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise SearchProviderError(
            f"Tavily Search returned HTTP {exc.code}: {message}"
        ) from exc
    except (URLError, TimeoutError) as exc:
        raise SearchProviderError(f"Failed to call Tavily Search: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SearchProviderError("Tavily Search returned invalid JSON.") from exc


def _brave_web_results(payload: JsonObject) -> list[JsonObject]:
    web = payload.get("web")
    if not isinstance(web, dict):
        return []
    results = web.get("results")
    if not isinstance(results, list):
        return []
    return [result for result in results if isinstance(result, dict)]


def _source_from_brave_result(
    result: JsonObject,
    *,
    retrieved_at: str,
    freshness_days: int | None,
    ) -> SourceMaterial:
    title = _string_field(result, "title") or "Untitled Brave result"
    url = _string_field(result, "url")
    published_at = _string_field(result, "page_age") or _string_field(result, "age")
    description = _string_field(result, "description")
    extra_snippets = result.get("extra_snippets")
    text_parts = [part for part in [description] if part]
    if isinstance(extra_snippets, list):
        text_parts.extend(item for item in extra_snippets if isinstance(item, str))
    text = _compose_provider_text(text_parts, fallback=title)
    return SourceMaterial(
        title=title,
        url=url,
        source_type="web_search_result",
        published_at=published_at,
        text=text,
        retrieved_at=retrieved_at,
        source_date_basis="brave_result_age" if published_at else None,
        staleness_note=_brave_staleness_note(
            published_at=published_at,
            freshness_days=freshness_days,
        ),
    )


def _tavily_results(payload: JsonObject) -> list[JsonObject]:
    results = payload.get("results")
    if not isinstance(results, list):
        return []
    return [result for result in results if isinstance(result, dict)]


def _source_from_tavily_result(
    result: JsonObject,
    *,
    retrieved_at: str,
    freshness_days: int | None,
) -> SourceMaterial:
    title = _string_field(result, "title") or "Untitled Tavily result"
    url = _string_field(result, "url")
    published_at = (
        _string_field(result, "published_date")
        or _string_field(result, "date")
    )
    content = _string_field(result, "content")
    raw_content = _string_field(result, "raw_content")
    text = _compose_provider_text([content, raw_content], fallback=title)
    return SourceMaterial(
        title=title,
        url=url,
        source_type="web_search_result",
        published_at=published_at,
        text=text,
        retrieved_at=retrieved_at,
        source_date_basis="tavily_published_date" if published_at else None,
        staleness_note=_tavily_staleness_note(
            published_at=published_at,
            freshness_days=freshness_days,
        ),
    )


def _string_field(payload: JsonObject, key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value.strip() else None


def _compose_provider_text(parts: list[str | None], *, fallback: str) -> str:
    normalized_parts: list[str] = []
    for part in parts:
        if not part:
            continue
        normalized = _normalize_provider_text(part)
        if normalized:
            normalized_parts.append(normalized)
    combined = "\n".join(normalized_parts)
    if not combined:
        return _normalize_provider_text(fallback) or fallback
    if len(combined) <= MAX_PROVIDER_TEXT_CHARS:
        return combined
    truncated = combined[:MAX_PROVIDER_TEXT_CHARS].rstrip()
    return (
        f"{truncated}\n\n"
        "[source text truncated before prompting to limit untrusted content size]"
    )


def _normalize_provider_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    normalized = re.sub(r"[ \t]{2,}", " ", normalized)
    return normalized.strip()


def _brave_staleness_note(
    *,
    published_at: str | None,
    freshness_days: int | None,
) -> str | None:
    if not published_at:
        return "Brave result did not expose a publication or page age date."
    if freshness_days is None:
        return None
    return f"Freshness window requested: {freshness_days} days."


def _tavily_staleness_note(
    *,
    published_at: str | None,
    freshness_days: int | None,
) -> str | None:
    if not published_at:
        return "Tavily result did not expose a publication date."
    if freshness_days is None:
        return None
    return f"Freshness window requested: {freshness_days} days."


def _tavily_time_range(freshness_days: int) -> str:
    if freshness_days <= 1:
        return "day"
    if freshness_days <= 7:
        return "week"
    if freshness_days <= 31:
        return "month"
    return "year"


def _compact_search_query(*, company: str, query: str, max_length: int) -> str:
    """Build a provider-safe query while preserving high-signal terms."""

    raw_parts = _query_parts(query)
    terms: list[str] = [company.strip()] if company.strip() else []
    seen: set[str] = {
        term.lower()
        for term in _terms_for_query(company)
    }
    for part in raw_parts:
        for term in _terms_for_query(part):
            key = term.lower()
            if key not in seen:
                terms.append(term)
                seen.add(key)

    compact = " ".join(terms).strip()
    if len(compact) <= max_length:
        return compact

    trimmed_terms: list[str] = []
    for term in terms:
        candidate = " ".join([*trimmed_terms, term]).strip()
        if len(candidate) > max_length:
            break
        trimmed_terms.append(term)
    if trimmed_terms:
        return " ".join(trimmed_terms)
    return compact[:max_length].rstrip()


def _query_parts(query: str) -> list[str]:
    lines = [line.strip() for line in query.splitlines() if line.strip()]
    if len(lines) <= 1:
        return lines

    topic = lines[0]
    brief = " ".join(lines[1:])
    return [topic, brief]


def _terms_for_query(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9&.+/-]*", text)
    stop_words = {
        "company",
        "question",
        "source",
        "types",
        "useful",
        "evidence",
        "investigate",
        "investigation",
        "current",
        "publicly",
        "available",
        "focusing",
        "regarding",
        "detailed",
        "claimed",
        "market",
    }
    return [
        word
        for word in words
        if len(word) >= 3 and word.lower() not in stop_words
    ]


def _terms(text: str) -> set[str]:
    return {
        term
        for term in re.findall(r"[a-zA-Z0-9]+", text.lower())
        if len(term) >= 4
    }
