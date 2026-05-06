"""Abstract SearchStrategy interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp_guardian.index import SearchResult, ToolEntry


class SearchStrategy(ABC):
    """Base class for tool search implementations.

    Subclass this to provide custom search logic (keyword, fuzzy,
    embedding-based, etc.). The proxy ships with KeywordSearch as
    the default.
    """

    @abstractmethod
    def search(
        self,
        query: str,
        entries: dict[str, ToolEntry],
    ) -> list[SearchResult]:
        """Search tool entries and return matches sorted by relevance.

        Args:
            query: Natural language search query.
            entries: Dict of tool_name -> ToolEntry to search over.

        Returns:
            Matching results sorted by relevance (best first).
        """
        ...
