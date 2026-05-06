"""Verify upstream MCP servers are accessible and returning real data.

Usage:
    uv run python scripts/verify_upstream.py
    uv run python scripts/verify_upstream.py --skip-github

Reads from .env:
    POSTGRES_MCP_URL  — MCP server URL (default: http://localhost:3000/mcp)
    GITHUB_TOKEN      — GitHub PAT for direct GitHub MCP access

Local docker alternative for PostgreSQL MCP:
    docker run --rm -p 3000:3000 -e POSTGRES_URL="$POSTGRES_URL" \\
      writenotenow/postgres-mcp:latest --transport http --port 3000
"""

from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()

POSTGRES_MCP_URL_DEFAULT = "http://localhost:3000/mcp"
GITHUB_MCP_URL = "https://api.githubcopilot.com/mcp/"

MIN_POSTGRES_TOOLS = 200
MIN_GITHUB_TOOLS = 30


def _get_postgres_mcp_url() -> str:
    """Resolve PostgreSQL MCP URL from env or fall back to localhost."""
    return os.environ.get("POSTGRES_MCP_URL", POSTGRES_MCP_URL_DEFAULT)


async def verify_postgres() -> bool:
    """Connect to PostgreSQL MCP, list tools, and call pg_list_tables."""
    from fastmcp import Client

    url = _get_postgres_mcp_url()
    print(f"\n--- PostgreSQL MCP ({url}) ---")
    try:
        async with Client(url) as client:
            tools = await client.list_tools()
            tool_count = len(tools)
            print(f"  Tools found: {tool_count}")

            if tool_count < MIN_POSTGRES_TOOLS:
                print(f"  FAIL: Expected >= {MIN_POSTGRES_TOOLS} tools, got {tool_count}")
                return False

            print(f"  OK: {tool_count} tools (>= {MIN_POSTGRES_TOOLS})")

            result = await client.call_tool("pg_list_tables", {})
            tables_text = "".join(block.text for block in result.content if hasattr(block, "text"))
            if not tables_text.strip():
                print("  FAIL: pg_list_tables returned empty result")
                return False

            preview_lines = tables_text.strip().splitlines()[:10]
            print("  pg_list_tables preview:")
            for line in preview_lines:
                print(f"    {line}")
            if len(tables_text.strip().splitlines()) > 10:
                print("    ...")

            print("  OK: pg_list_tables returned real data")
            return True

    except Exception as exc:
        print(f"  FAIL: {exc}")
        return False


async def verify_github() -> bool:
    """Connect to GitHub MCP directly using a PAT, list tools."""
    from fastmcp import Client

    github_token = os.environ.get("GITHUB_TOKEN", "")
    if not github_token:
        print("\n--- GitHub MCP ---")
        print("  SKIP: GITHUB_TOKEN not set")
        return True

    print(f"\n--- GitHub MCP ({GITHUB_MCP_URL}) ---")
    try:
        async with Client(GITHUB_MCP_URL, auth=github_token) as client:
            tools = await client.list_tools()
            tool_count = len(tools)
            print(f"  Tools found: {tool_count}")

            if tool_count < MIN_GITHUB_TOOLS:
                print(f"  FAIL: Expected >= {MIN_GITHUB_TOOLS} tools, got {tool_count}")
                return False

            print(f"  OK: {tool_count} tools (>= {MIN_GITHUB_TOOLS})")
            print("  First 5 tools:")
            for tool in tools[:5]:
                print(f"    - {tool.name}")
            return True

    except Exception as exc:
        print(f"  FAIL: {exc}")
        return False


async def main() -> int:
    """Run all upstream verifications. Returns 0 on success, 1 on failure."""
    skip_github = "--skip-github" in sys.argv

    print("=== Upstream Server Verification ===")

    postgres_ok = await verify_postgres()

    if skip_github:
        print("\n--- GitHub MCP ---")
        print("  SKIP: --skip-github flag")
        github_ok = True
    else:
        github_ok = await verify_github()

    print("\n=== Summary ===")
    status_pg = "OK" if postgres_ok else "FAIL"
    status_gh = "OK" if github_ok else "FAIL"
    if skip_github:
        status_gh = "SKIP"
    print(f"  PostgreSQL MCP: {status_pg}")
    print(f"  GitHub MCP:     {status_gh}")

    if postgres_ok and github_ok:
        print("\nAll checks passed.")
        return 0
    else:
        print("\nSome checks failed.")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
