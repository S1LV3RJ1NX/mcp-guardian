"""Experiment 1: Token Cost Comparison.

Measures tokens consumed at session startup across four modes:
  1. Direct — all tool schemas from upstream servers loaded upfront
  2. Proxy startup — only the 3 meta-tool schemas
  3. Proxy after search — meta-tools + one search_tools result
  4. Proxy after search + get_schema — meta-tools + search + one full schema

Prerequisites:
  - Upstream MCP servers running (PostgreSQL MCP, optionally GitHub MCP)
  - mcp-guardian proxy running: uv run mcp-guardian --scope support-agent

Usage:
  uv run python benchmarks/experiment-1-token-cost/bench_tokens.py
  uv run python benchmarks/experiment-1-token-cost/bench_tokens.py --skip-github
  uv run python benchmarks/experiment-1-token-cost/bench_tokens.py --proxy-url http://localhost:9000/mcp
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent / "src"))

from mcp_guardian.tokens import count_tokens  # noqa: E402

RESULTS_DIR = Path(__file__).parent
DEFAULT_PROXY_URL = "http://localhost:9000/mcp"


async def measure_direct(
    postgres_url: str,
    github_url: str | None,
    github_token: str | None,
) -> tuple[int, dict[str, int]]:
    """Connect directly to upstream servers, count total schema tokens.

    Returns (total_tokens, {server_name: tool_count}).
    """
    from fastmcp import Client

    servers: list[tuple[str, str, str | None]] = [("postgres", postgres_url, None)]
    if github_url and github_token:
        servers.append(("github", github_url, github_token))

    total = 0
    tool_counts: dict[str, int] = {}

    for name, url, auth in servers:
        try:
            async with Client(url, auth=auth) as client:
                tools = await client.list_tools()
                tool_counts[name] = len(tools)
                for tool in tools:
                    schema_json = json.dumps(tool.model_dump(), separators=(",", ":"))
                    total += count_tokens(schema_json)
        except Exception as exc:
            print(f"  WARNING: Could not connect to {name} at {url}: {exc}")
            tool_counts[name] = 0

    return total, tool_counts


async def measure_proxy_startup(proxy_url: str) -> int:
    """Connect to proxy, count only the 3 meta-tool schema tokens."""
    from fastmcp import Client

    async with Client(proxy_url) as client:
        tools = await client.list_tools()
        total = 0
        for tool in tools:
            schema_json = json.dumps(tool.model_dump(), separators=(",", ":"))
            total += count_tokens(schema_json)
        return total


def _result_text(result: object) -> str:
    """Extract text content from a CallToolResult."""
    if hasattr(result, "content"):
        parts = []
        for item in result.content:
            if hasattr(item, "text"):
                parts.append(item.text)
        return " ".join(parts)
    return str(result)


async def measure_proxy_after_search(proxy_url: str) -> int:
    """Proxy startup + one search_tools call."""
    from fastmcp import Client

    async with Client(proxy_url) as client:
        tools = await client.list_tools()
        startup = sum(
            count_tokens(json.dumps(t.model_dump(), separators=(",", ":"))) for t in tools
        )

        result = await client.call_tool("search_tools", {"query": "issues"})
        search_tokens = count_tokens(_result_text(result))

        return startup + search_tokens


async def measure_proxy_after_schema(proxy_url: str) -> int:
    """Proxy startup + search + get_schema for one tool."""
    from fastmcp import Client

    async with Client(proxy_url) as client:
        tools = await client.list_tools()
        startup = sum(
            count_tokens(json.dumps(t.model_dump(), separators=(",", ":"))) for t in tools
        )

        search_result = await client.call_tool("search_tools", {"query": "issues"})
        search_tokens = count_tokens(_result_text(search_result))

        schema_result = await client.call_tool(
            "get_schema",
            {"tool_name": "list_issues"},
        )
        schema_tokens = count_tokens(_result_text(schema_result))

        return startup + search_tokens + schema_tokens


async def run_experiment(
    proxy_url: str,
    skip_github: bool,
) -> dict[str, int]:
    """Run all four measurement modes and return results."""
    postgres_url = os.environ.get("POSTGRES_MCP_URL", "http://localhost:3000/mcp")
    github_url: str | None = "https://api.githubcopilot.com/mcp/"
    github_token: str | None = os.environ.get("GITHUB_TOKEN")

    if skip_github or not github_token:
        github_url = None
        github_token = None
        if not skip_github:
            print("  NOTE: GITHUB_TOKEN not set, skipping GitHub MCP")

    print("\n=== Experiment 1: Token Cost Comparison ===\n")

    print("Step 1/4: Measuring direct connection token cost...")
    direct_tokens, tool_counts = await measure_direct(
        postgres_url,
        github_url,
        github_token,
    )
    total_tools = sum(tool_counts.values())
    for name, count in tool_counts.items():
        print(f"  {name}: {count} tools")
    print(f"  Total: {total_tools} tools, {direct_tokens:,} tokens\n")

    print("Step 2/4: Measuring proxy startup token cost...")
    proxy_startup = await measure_proxy_startup(proxy_url)
    print(f"  {proxy_startup:,} tokens (3 meta-tools)\n")

    print("Step 3/4: Measuring proxy after search...")
    proxy_search = await measure_proxy_after_search(proxy_url)
    print(f"  {proxy_search:,} tokens\n")

    print("Step 4/4: Measuring proxy after search + get_schema...")
    proxy_schema = await measure_proxy_after_schema(proxy_url)
    print(f"  {proxy_schema:,} tokens\n")

    return {
        "direct": direct_tokens,
        "proxy_startup": proxy_startup,
        "proxy_after_search": proxy_search,
        "proxy_after_schema": proxy_schema,
    }


def print_results(results: dict[str, int]) -> None:
    """Print a formatted results table."""
    direct = results["direct"]

    print(f"\n{'Mode':<30} {'Tokens':>10} {'vs Direct':>14}")
    print("-" * 57)
    for mode, tokens in results.items():
        if mode == "direct":
            savings = "baseline"
        elif direct > 0:
            savings = f"{(1 - tokens / direct) * 100:.1f}% saved"
        else:
            savings = "N/A"
        print(f"{mode:<30} {tokens:>10,} {savings:>14}")
    print()


def write_csv(results: dict[str, int]) -> Path:
    """Write results to CSV file."""
    csv_path = RESULTS_DIR / "token_costs.csv"
    direct = results["direct"]

    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["mode", "tokens", "savings_pct"])
        for mode, tokens in results.items():
            pct = round((1 - tokens / direct) * 100, 1) if mode != "direct" and direct > 0 else 0
            writer.writerow([mode, tokens, pct])

    return csv_path


def check_pass_criteria(results: dict[str, int]) -> bool:
    """Check if proxy startup savings > 95%."""
    direct = results["direct"]
    startup = results["proxy_startup"]
    if direct == 0:
        return False
    savings_pct = (1 - startup / direct) * 100
    passed = savings_pct > 95
    status = "PASS" if passed else "FAIL"
    print("Pass criteria: proxy startup savings > 95%")
    print(f"  Actual: {savings_pct:.1f}% — {status}")
    return passed


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(description="Experiment 1: Token Cost Comparison")
    parser.add_argument(
        "--proxy-url",
        default=DEFAULT_PROXY_URL,
        help=f"URL of the mcp-guardian proxy (default: {DEFAULT_PROXY_URL})",
    )
    parser.add_argument(
        "--skip-github",
        action="store_true",
        help="Skip GitHub MCP measurement",
    )
    args = parser.parse_args()

    results = asyncio.run(run_experiment(args.proxy_url, args.skip_github))
    print_results(results)
    csv_path = write_csv(results)
    print(f"Results saved to {csv_path}")
    passed = check_pass_criteria(results)

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
