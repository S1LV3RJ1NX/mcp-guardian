"""Tests for mcp_guardian.search.keyword."""

from __future__ import annotations

from mcp_guardian.index import ToolEntry
from mcp_guardian.search.keyword import KeywordSearch


def _entry(
    name: str,
    description: str = "",
    server: str = "test",
) -> ToolEntry:
    return ToolEntry(
        name=name,
        server=server,
        description=description,
        brief=description[:100],
        full_schema={"name": name},
        token_cost=10,
    )


def _build_entries(*entries: ToolEntry) -> dict[str, ToolEntry]:
    return {e.name: e for e in entries}


class TestKeywordSearch:
    """Tests for the KeywordSearch strategy."""

    def setup_method(self) -> None:
        self.search = KeywordSearch()
        self.entries = _build_entries(
            _entry("list_issues", "List issues in a GitHub repository"),
            _entry("create_issue", "Create a new issue in a repository"),
            _entry("pg_list_tables", "List all tables in the database"),
            _entry("pg_read_query", "Execute a read-only SQL query"),
            _entry("delete_file", "Delete a file from a repository"),
        )

    def test_finds_tools_by_name(self) -> None:
        """Keyword in tool name matches."""
        results = self.search.search("list", self.entries)
        names = [r.name for r in results]
        assert "list_issues" in names
        assert "pg_list_tables" in names

    def test_finds_tools_by_description(self) -> None:
        """Keyword in description matches."""
        results = self.search.search("database", self.entries)
        names = [r.name for r in results]
        assert "pg_list_tables" in names

    def test_no_matches_returns_empty(self) -> None:
        """Query with no keyword overlap returns empty list."""
        results = self.search.search("xyznonexistent", self.entries)
        assert results == []

    def test_exact_name_scores_higher(self) -> None:
        """An exact name match scores higher than a partial match."""
        entries = _build_entries(
            _entry("query", "Run a query"),
            _entry("pg_read_query", "Execute a read-only SQL query"),
        )
        results = self.search.search("query", entries)
        assert len(results) >= 2
        assert results[0].name == "query"

    def test_case_insensitive(self) -> None:
        """Search is case insensitive."""
        results = self.search.search("LIST", self.entries)
        names = [r.name for r in results]
        assert "list_issues" in names

    def test_empty_query_returns_empty(self) -> None:
        """Empty query string returns empty list."""
        results = self.search.search("", self.entries)
        assert results == []
