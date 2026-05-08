"""Search and source-material boundary.

The orchestration layer should depend on this module's small abstractions, not
on a specific web/search provider. Real providers can later adapt API responses
into `SourceMaterial` records.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Protocol


@dataclass(frozen=True)
class SourceMaterial:
    title: str
    url: str | None
    source_type: str
    published_at: str | None
    text: str


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


class DirectorySearchProvider:
    """Load local markdown/text files and rank them by simple lexical overlap."""

    def __init__(self, source_dir: str | Path) -> None:
        self.source_dir = Path(source_dir)

    def search(self, *, company: str, query: str, max_results: int = 5) -> list[SourceMaterial]:
        sources = [
            source_from_file(path)
            for path in self._source_files()
        ]
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


def source_from_file(path: str | Path, *, source_type: str = "user_supplied") -> SourceMaterial:
    """Load a local text/markdown file as source material."""

    source_path = Path(path)
    return SourceMaterial(
        title=source_path.name,
        url=None,
        source_type=source_type,
        published_at=None,
        text=source_path.read_text(encoding="utf-8"),
    )


def _score_source(source: SourceMaterial, *, company: str, query: str) -> int:
    haystack = " ".join([source.title, source.text]).lower()
    terms = _terms(f"{company} {query}")
    return sum(1 for term in terms if term in haystack)


def _terms(text: str) -> set[str]:
    return {
        term
        for term in re.findall(r"[a-zA-Z0-9]+", text.lower())
        if len(term) >= 4
    }
