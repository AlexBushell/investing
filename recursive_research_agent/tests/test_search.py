import tempfile
import unittest
from pathlib import Path

from app.search import (
    DirectorySearchProvider,
    FakeSearchProvider,
    SourceMaterial,
    source_from_file,
)


class SearchBoundaryTests(unittest.TestCase):
    def test_fake_search_provider_records_calls_and_limits_results(self):
        sources = [
            SourceMaterial(
                title=f"Source {index}",
                url=None,
                source_type="test",
                published_at=None,
                text=f"Text {index}",
            )
            for index in range(3)
        ]
        provider = FakeSearchProvider(sources)

        results = provider.search(
            company="Example Co",
            query="revenue quality",
            max_results=2,
        )

        self.assertEqual(["Source 0", "Source 1"], [
            source.title for source in results
        ])
        self.assertEqual(
            {
                "company": "Example Co",
                "query": "revenue quality",
                "max_results": 2,
            },
            provider.calls[0],
        )

    def test_source_from_file_loads_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "source.md"
            path.write_text("Source text.", encoding="utf-8")

            source = source_from_file(path, source_type="filing_excerpt")

        self.assertEqual("source.md", source.title)
        self.assertEqual("filing_excerpt", source.source_type)
        self.assertEqual("Source text.", source.text)

    def test_directory_search_provider_ranks_matching_sources(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_dir = Path(temp_dir)
            (source_dir / "revenue.md").write_text(
                "Example Co subscription revenue and gross margin.",
                encoding="utf-8",
            )
            (source_dir / "unrelated.md").write_text(
                "Other Co litigation update.",
                encoding="utf-8",
            )

            provider = DirectorySearchProvider(source_dir)
            results = provider.search(
                company="Example Co",
                query="revenue gross margin",
                max_results=2,
            )

        self.assertEqual(["revenue.md"], [source.title for source in results])


if __name__ == "__main__":
    unittest.main()
