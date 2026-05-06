"""Experiment 5: Scope Security Validation.

Verifies that blocked tools are truly invisible across all three
meta-tools (search_tools, get_schema, execute_tool).

Prerequisites:
  - mcp-guardian proxy running with support-agent scope

Usage:
  uv run python benchmarks/experiment-5-security/bench_security.py
  uv run python benchmarks/experiment-5-security/bench_security.py --proxy-url http://localhost:9000/mcp
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path

RESULTS_DIR = Path(__file__).parent
DEFAULT_PROXY_URL = "http://localhost:9000/mcp"

BLOCKED_TOOLS: dict[str, list[str]] = {
    "github": [
        "delete_file",
        "fork_repository",
        "push_files",
        "create_repository",
    ],
    "postgres": [
        "pg_drop_table",
        "pg_truncate",
        "pg_write_query",
        "pg_vacuum",
        "pg_terminate_backend",
    ],
}


@dataclass
class ToolTestResult:
    """Result of testing one blocked tool across all vectors."""

    server: str
    tool: str
    search_hidden: bool = False
    schema_blocked: bool = False
    execute_blocked: bool = False

    @property
    def all_pass(self) -> bool:
        return self.search_hidden and self.schema_blocked and self.execute_blocked


def parse_tool_names(result: object) -> list[str]:
    """Extract tool names from a search_tools CallToolResult."""
    if hasattr(result, "content"):
        for item in result.content:
            if hasattr(item, "text"):
                try:
                    data = json.loads(item.text)
                    if isinstance(data, list):
                        return [e["name"] for e in data if isinstance(e, dict) and "name" in e]
                except (json.JSONDecodeError, KeyError):
                    pass
    return []


def result_text(result: object) -> str:
    """Extract text from a CallToolResult."""
    if hasattr(result, "content"):
        parts = []
        for item in result.content:
            if hasattr(item, "text"):
                parts.append(item.text)
        return " ".join(parts)
    return str(result)


async def test_tool(
    client: object,
    server: str,
    tool_name: str,
) -> ToolTestResult:
    """Test one blocked tool across all three vectors."""
    tr = ToolTestResult(server=server, tool=tool_name)

    # Vector 1: search_tools — tool should not appear in results
    search_keyword = tool_name.replace("_", " ").split()[0]
    search_result = await client.call_tool(  # type: ignore[union-attr]
        "search_tools",
        {"query": search_keyword},
    )
    found_names = parse_tool_names(search_result)
    tr.search_hidden = tool_name not in found_names

    # Vector 2: get_schema — should return error
    schema_result = await client.call_tool(  # type: ignore[union-attr]
        "get_schema",
        {"tool_name": tool_name},
    )
    schema_text = result_text(schema_result)
    tr.schema_blocked = "error" in schema_text.lower() or "not found" in schema_text.lower()

    # Vector 3: execute_tool — should return TOOL_NOT_IN_SCOPE
    exec_result = await client.call_tool(  # type: ignore[union-attr]
        "execute_tool",
        {"tool_name": tool_name, "params": {}},
    )
    exec_text = result_text(exec_result)
    tr.execute_blocked = (
        "TOOL_NOT_IN_SCOPE" in exec_text
        or "not found" in exec_text.lower()
        or "error" in exec_text.lower()
    )

    return tr


async def run_experiment(proxy_url: str) -> list[ToolTestResult]:
    """Run security validation against all blocked tools."""
    from fastmcp import Client

    print("\n=== Experiment 5: Scope Security Validation ===\n")
    print(f"  Proxy: {proxy_url}\n")

    results: list[ToolTestResult] = []

    async with Client(proxy_url) as client:
        for server, tools in BLOCKED_TOOLS.items():
            print(f"{server.upper()} blocked tools:")
            header = (
                f"  {'Blocked Tool':<25} {'search_tools':>13}"
                f" {'get_schema':>11} {'execute_tool':>13}"
            )
            print(header)
            print(f"  {'-' * (len(header) - 2)}")

            for tool_name in tools:
                tr = await test_tool(client, server, tool_name)
                results.append(tr)

                s_icon = "HIDDEN" if tr.search_hidden else "LEAKED"
                g_icon = "BLOCKED" if tr.schema_blocked else "LEAKED"
                e_icon = "BLOCKED" if tr.execute_blocked else "LEAKED"
                print(f"  {tool_name:<25} {s_icon:>13} {g_icon:>11} {e_icon:>13}")

            print()

    return results


def print_summary(results: list[ToolTestResult]) -> None:
    """Print overall summary."""
    total = len(results) * 3
    passed = sum(
        int(r.search_hidden) + int(r.schema_blocked) + int(r.execute_blocked) for r in results
    )
    failed = total - passed

    if failed == 0:
        print("Result: All blocked tools are invisible across all vectors.")
    else:
        print(f"Result: {failed} SECURITY FAILURES detected!")
        for r in results:
            if not r.all_pass:
                issues = []
                if not r.search_hidden:
                    issues.append("search leaked")
                if not r.schema_blocked:
                    issues.append("schema leaked")
                if not r.execute_blocked:
                    issues.append("execute leaked")
                print(f"  {r.tool}: {', '.join(issues)}")
    print()


def write_csv(results: list[ToolTestResult]) -> Path:
    """Write results to CSV file."""
    csv_path = RESULTS_DIR / "security.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "server",
                "tool",
                "search_hidden",
                "schema_blocked",
                "execute_blocked",
                "all_pass",
            ]
        )
        for r in results:
            writer.writerow(
                [
                    r.server,
                    r.tool,
                    r.search_hidden,
                    r.schema_blocked,
                    r.execute_blocked,
                    r.all_pass,
                ]
            )
    return csv_path


def check_pass_criteria(results: list[ToolTestResult]) -> bool:
    """Check if 100% of tests pass."""
    all_pass = all(r.all_pass for r in results)
    total_checks = len(results) * 3
    passed_checks = sum(
        int(r.search_hidden) + int(r.schema_blocked) + int(r.execute_blocked) for r in results
    )
    status = "PASS" if all_pass else "FAIL"
    print("Pass criteria: 100% of blocked tools invisible")
    print(f"  {passed_checks}/{total_checks} checks passed — {status}")
    return all_pass


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Experiment 5: Scope Security Validation",
    )
    parser.add_argument(
        "--proxy-url",
        default=DEFAULT_PROXY_URL,
        help=f"URL of the mcp-guardian proxy (default: {DEFAULT_PROXY_URL})",
    )
    args = parser.parse_args()

    results = asyncio.run(run_experiment(args.proxy_url))
    print_summary(results)
    csv_path = write_csv(results)
    print(f"Results saved to {csv_path}")
    passed = check_pass_criteria(results)

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
