"""Tool index: catalog of scope-filtered tools."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mcp_guardian.search.keyword import KeywordSearch
from mcp_guardian.tokens import count_schema_tokens

if TYPE_CHECKING:
    from mcp_guardian.config import GuardianConfig
    from mcp_guardian.search.base import SearchStrategy
    from mcp_guardian.upstream import UpstreamManager

logger = logging.getLogger(__name__)

MAX_BRIEF_LENGTH = 100


@dataclass
class ToolEntry:
    """A single tool in the index."""

    name: str
    server: str
    description: str
    brief: str
    full_schema: dict[str, Any]
    token_cost: int


@dataclass
class SearchResult:
    """A search hit returned to the caller."""

    name: str
    server: str
    brief: str


def _make_brief(description: str) -> str:
    """Extract first sentence of description, truncated to MAX_BRIEF_LENGTH chars."""
    if not description:
        return ""
    first_sentence = description.split(".")[0].strip()
    if len(first_sentence) > MAX_BRIEF_LENGTH:
        return first_sentence[: MAX_BRIEF_LENGTH - 3] + "..."
    return first_sentence


class ToolIndex:
    """Searchable catalog of scope-filtered tools.

    Built at startup by probing upstream servers and filtering
    by the active scope's allowed_tools / blocked_tools rules.
    """

    def __init__(self, search_strategy: SearchStrategy | None = None) -> None:
        self.entries: dict[str, ToolEntry] = {}
        self.tokens_saved: int = 0
        self._excluded_count: int = 0
        self._search: SearchStrategy = search_strategy or KeywordSearch()
        self._deferred_servers: list[str] = []

    async def build(self, config: GuardianConfig, upstream: UpstreamManager) -> None:
        """Probe upstream servers, filter by scope, build the index.

        Args:
            config: The loaded guardian config with active scope set.
            upstream: The upstream manager to probe servers through.
        """
        scope = config.scopes[config.active_scope]

        for server_name, scope_server in scope.servers.items():
            try:
                tools = await upstream.list_tools(server_name, interactive=False)
            except Exception as exc:
                logger.warning(
                    "Server '%s': skipped at startup (%s). "
                    "Tools will be indexed on first authenticated call.",
                    server_name,
                    exc,
                )
                self._deferred_servers.append(server_name)
                continue
            logger.info(
                "Server '%s': %d tools upstream, filtering by scope",
                server_name,
                len(tools),
            )

            allowed = scope_server.allowed_tools
            blocked = set(scope_server.blocked_tools)

            for tool in tools:
                schema = tool.model_dump()
                tokens = count_schema_tokens(schema)

                if _is_tool_allowed(tool.name, allowed, blocked):
                    self.entries[tool.name] = ToolEntry(
                        name=tool.name,
                        server=server_name,
                        description=tool.description or "",
                        brief=_make_brief(tool.description or ""),
                        full_schema=schema,
                        token_cost=tokens,
                    )
                else:
                    self.tokens_saved += tokens
                    self._excluded_count += 1

            included = sum(1 for e in self.entries.values() if e.server == server_name)
            logger.info(
                "Server '%s': %d tools included, %d excluded by scope",
                server_name,
                included,
                len(tools) - included,
            )

    async def index_deferred(self, config: GuardianConfig, upstream: UpstreamManager) -> list[str]:
        """Try to index servers that were deferred at startup (e.g. OAuth).

        Returns:
            List of server names that were successfully indexed.
        """
        if not self._deferred_servers:
            return []

        scope = config.scopes[config.active_scope]
        indexed: list[str] = []

        for server_name in list(self._deferred_servers):
            scope_server = scope.servers.get(server_name)
            if scope_server is None:
                continue
            try:
                tools = await upstream.list_tools(server_name)
            except Exception:
                continue

            allowed = scope_server.allowed_tools
            blocked = set(scope_server.blocked_tools)

            for tool in tools:
                schema = tool.model_dump()
                tokens = count_schema_tokens(schema)
                if _is_tool_allowed(tool.name, allowed, blocked):
                    self.entries[tool.name] = ToolEntry(
                        name=tool.name,
                        server=server_name,
                        description=tool.description or "",
                        brief=_make_brief(tool.description or ""),
                        full_schema=schema,
                        token_cost=tokens,
                    )
                else:
                    self.tokens_saved += tokens
                    self._excluded_count += 1

            self._deferred_servers.remove(server_name)
            indexed.append(server_name)
            logger.info(
                "Server '%s': deferred indexing complete (%d tools)",
                server_name,
                len(tools),
            )

        return indexed

    def search(self, query: str) -> list[SearchResult]:
        """Search indexed tools by query.

        Args:
            query: Search keywords.

        Returns:
            Matching results sorted by relevance.
        """
        return self._search.search(query, self.entries)

    def get_schema(self, tool_name: str) -> dict[str, Any] | None:
        """Get the full schema for a specific tool.

        Args:
            tool_name: Exact tool name.

        Returns:
            The tool's full schema dict, or None if not in scope.
        """
        entry = self.entries.get(tool_name)
        return entry.full_schema if entry else None

    def get_server_for_tool(self, tool_name: str) -> str | None:
        """Look up which upstream server owns a tool.

        Args:
            tool_name: Exact tool name.

        Returns:
            Server name, or None if the tool is not indexed.
        """
        entry = self.entries.get(tool_name)
        return entry.server if entry else None

    @property
    def stats(self) -> dict[str, Any]:
        """Return index statistics."""
        return {
            "tools_indexed": len(self.entries),
            "tools_excluded": self._excluded_count,
            "tokens_saved": self.tokens_saved,
            "servers": list({e.server for e in self.entries.values()}),
        }


def _is_tool_allowed(
    tool_name: str,
    allowed: list[str] | str,
    blocked: set[str],
) -> bool:
    """Check whether a tool passes the scope filter.

    Args:
        tool_name: Name of the tool to check.
        allowed: Either "*" (all) or an explicit list of allowed names.
        blocked: Set of blocked tool names (only applies when allowed="*").

    Returns:
        True if the tool should be included in the index.
    """
    if allowed == "*":
        return tool_name not in blocked
    return tool_name in allowed
