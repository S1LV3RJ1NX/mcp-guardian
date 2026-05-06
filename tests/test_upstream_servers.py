"""Integration tests for upstream MCP servers.

These tests require real servers to be running and are marked with
@pytest.mark.integration. They skip gracefully if servers are unreachable.

POSTGRES_MCP_URL env var controls the PostgreSQL MCP endpoint.
GITHUB_TOKEN env var provides the PAT for GitHub MCP.

Run: uv run pytest tests/test_upstream_servers.py -v -m integration
"""

from __future__ import annotations

import os
import socket
from urllib.parse import urlparse

import pytest
from dotenv import load_dotenv

load_dotenv()

POSTGRES_MCP_URL_DEFAULT = "http://localhost:3000/mcp"
GITHUB_MCP_URL = "https://api.githubcopilot.com/mcp/"

MIN_POSTGRES_TOOLS = 200
MIN_GITHUB_TOOLS = 30


def _get_postgres_mcp_url() -> str:
    """Resolve PostgreSQL MCP URL from env or fall back to localhost."""
    return os.environ.get("POSTGRES_MCP_URL", POSTGRES_MCP_URL_DEFAULT)


def _is_reachable(url: str, timeout: float = 2.0) -> bool:
    """Check if a TCP connection to the host:port of a URL succeeds."""
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, TimeoutError):
        return False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_mcp_accessible() -> None:
    """PostgreSQL MCP returns 200+ tools and real table data."""
    url = _get_postgres_mcp_url()
    if not _is_reachable(url):
        pytest.skip(f"postgres-mcp not reachable at {url}")

    from fastmcp import Client

    async with Client(url) as client:
        tools = await client.list_tools()
        assert len(tools) >= MIN_POSTGRES_TOOLS, (
            f"Expected >= {MIN_POSTGRES_TOOLS} tools, got {len(tools)}"
        )

        result = await client.call_tool("pg_list_tables", {})
        tables_text = "".join(block.text for block in result.content if hasattr(block, "text"))
        assert tables_text.strip(), "pg_list_tables returned empty result"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_github_mcp_accessible() -> None:
    """GitHub MCP via PAT returns 30+ tools."""
    github_token = os.environ.get("GITHUB_TOKEN", "")
    if not github_token or github_token == "ghp_your_token_here":
        pytest.skip("GITHUB_TOKEN not set (or still placeholder)")

    from fastmcp import Client

    async with Client(GITHUB_MCP_URL, auth=github_token) as client:
        tools = await client.list_tools()
        assert len(tools) >= MIN_GITHUB_TOOLS, (
            f"Expected >= {MIN_GITHUB_TOOLS} tools, got {len(tools)}"
        )
