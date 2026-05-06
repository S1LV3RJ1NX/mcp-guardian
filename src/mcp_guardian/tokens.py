"""Token counter for schema cost measurement."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp_guardian.index import ToolIndex

logger = logging.getLogger(__name__)

# Lazy-loaded tiktoken encoder. Falls back to a ~0.75 words/token
# approximation when tiktoken can't download its encoding data.
_encoder: Any = None
_encoder_loaded = False


def _get_encoder() -> Any:
    """Lazy-load the tiktoken encoder, returning None on failure."""
    global _encoder, _encoder_loaded  # noqa: PLW0603
    if _encoder_loaded:
        return _encoder
    _encoder_loaded = True
    try:
        import tiktoken

        _encoder = tiktoken.get_encoding("cl100k_base")
    except Exception:
        logger.debug("tiktoken unavailable, using word-count approximation")
        _encoder = None
    return _encoder


def _approx_tokens(text: str) -> int:
    """Approximate token count: ~1 token per 4 characters.

    For JSON-heavy content (tool schemas), character-based estimation
    is more reliable than word-based since JSON has many punctuation
    tokens (braces, colons, quotes).
    """
    return max(1, len(text) // 4)


META_TOOL_SCHEMAS = [
    {
        "name": "search_tools",
        "description": (
            "Search available tools by keyword. Returns tool names and brief descriptions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Search keywords"}},
            "required": ["query"],
        },
    },
    {
        "name": "get_schema",
        "description": "Get the full parameter schema for a specific tool.",
        "inputSchema": {
            "type": "object",
            "properties": {"tool_name": {"type": "string", "description": "Exact tool name"}},
            "required": ["tool_name"],
        },
    },
    {
        "name": "execute_tool",
        "description": "Execute a tool with the given parameters.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tool_name": {"type": "string", "description": "Exact tool name"},
                "params": {"type": "object", "description": "Tool parameters as JSON object"},
            },
            "required": ["tool_name", "params"],
        },
    },
]


def count_tokens(text: str) -> int:
    """Count tokens in a string using cl100k_base encoding.

    Falls back to a word-count approximation (~0.75 tokens/word)
    when tiktoken is unavailable.

    Args:
        text: The string to tokenize.

    Returns:
        Number of tokens.
    """
    enc = _get_encoder()
    if enc is not None:
        return len(enc.encode(text))
    return _approx_tokens(text)


def count_schema_tokens(schema: dict[str, Any]) -> int:
    """Count tokens in a tool schema dict (JSON-serialized).

    Args:
        schema: A tool schema dictionary.

    Returns:
        Number of tokens in the JSON representation.
    """
    return count_tokens(json.dumps(schema, separators=(",", ":")))


def build_meta_tools_token_count() -> int:
    """Return the approximate token cost of the 3 meta-tool schemas."""
    return sum(count_schema_tokens(s) for s in META_TOOL_SCHEMAS)


def savings_report(index: ToolIndex) -> dict[str, Any]:
    """Generate a token savings report from a built ToolIndex.

    Args:
        index: A built ToolIndex instance.

    Returns:
        Dict with direct_tokens, proxy_tokens, savings_pct,
        tools_in_scope, and tools_excluded.
    """
    in_scope_tokens = sum(e.token_cost for e in index.entries.values())
    direct_tokens = in_scope_tokens + index.tokens_saved
    proxy_tokens = build_meta_tools_token_count()

    savings_pct = (1 - proxy_tokens / direct_tokens) * 100 if direct_tokens > 0 else 0.0

    return {
        "direct_tokens": direct_tokens,
        "proxy_tokens": proxy_tokens,
        "savings_pct": round(savings_pct, 1),
        "tools_in_scope": len(index.entries),
        "tools_excluded": index._excluded_count,
    }
