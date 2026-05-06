"""Keyword search implementation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp_guardian.search.base import SearchStrategy

if TYPE_CHECKING:
    from mcp_guardian.index import SearchResult, ToolEntry

SCORE_EXACT_NAME = 3
SCORE_NAME_CONTAINS = 2
SCORE_DESC_CONTAINS = 1


class KeywordSearch(SearchStrategy):
    """Simple keyword-based search over tool names and descriptions.

    Splits the query into keywords and scores each tool entry:
    - Exact name match: 3 points per keyword
    - Name contains keyword: 2 points per keyword
    - Description contains keyword: 1 point per keyword

    Results are sorted by total score (descending). Tools with
    zero score are excluded.
    """

    def search(
        self,
        query: str,
        entries: dict[str, ToolEntry],
    ) -> list[SearchResult]:
        """Search tool entries by keyword matching.

        Args:
            query: Space-separated keywords to search for.
            entries: Dict of tool_name -> ToolEntry.

        Returns:
            Matching results sorted by relevance score (highest first).
        """
        from mcp_guardian.index import SearchResult

        keywords = query.lower().split()
        if not keywords:
            return []

        scored: list[tuple[int, ToolEntry]] = []

        for entry in entries.values():
            score = 0
            name_lower = entry.name.lower()
            desc_lower = entry.description.lower()

            for kw in keywords:
                if kw == name_lower:
                    score += SCORE_EXACT_NAME
                elif kw in name_lower:
                    score += SCORE_NAME_CONTAINS
                elif kw in desc_lower:
                    score += SCORE_DESC_CONTAINS

            if score > 0:
                scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)

        return [
            SearchResult(name=entry.name, server=entry.server, brief=entry.brief)
            for _, entry in scored
        ]
