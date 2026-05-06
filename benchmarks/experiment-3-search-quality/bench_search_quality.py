"""Experiment 3: Search Quality.

Measures how well the proxy's keyword search finds the right tools.

Runs 20 test queries against search_tools, checks if expected tools
appear in results, and reports hit rate, precision@1, precision@3,
plus a miss analysis.

Prerequisites:
  - mcp-guardian proxy running with desired scope

Usage:
  uv run python benchmarks/experiment-3-search-quality/bench_search_quality.py
  uv run python benchmarks/experiment-3-search-quality/bench_search_quality.py --proxy-url http://localhost:9000/mcp
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

RESULTS_DIR = Path(__file__).parent
DEFAULT_PROXY_URL = "http://localhost:9000/mcp"


@dataclass
class QueryResult:
    """Result of a single query evaluation."""

    query: str
    expected: list[str]
    returned: list[str]
    hit: bool = False
    precision_at_1: bool = False
    precision_at_3: bool = False
    scope_blocked: bool = False
    miss_reason: str = ""


@dataclass
class ScopeReport:
    """Aggregated metrics for one scope."""

    scope: str
    total_queries: int = 0
    applicable_queries: int = 0
    scope_blocked: int = 0
    hits: int = 0
    p1_hits: int = 0
    p3_hits: int = 0
    results: list[QueryResult] = field(default_factory=list)
    misses: list[QueryResult] = field(default_factory=list)

    @property
    def hit_rate(self) -> float:
        return self.hits / self.applicable_queries * 100 if self.applicable_queries else 0

    @property
    def precision_at_1(self) -> float:
        return self.p1_hits / self.applicable_queries * 100 if self.applicable_queries else 0

    @property
    def precision_at_3(self) -> float:
        return self.p3_hits / self.applicable_queries * 100 if self.applicable_queries else 0


def parse_tool_names(result: object) -> list[str]:
    """Extract tool names from a search_tools CallToolResult.

    The proxy returns a list of dicts with 'name' keys, serialized
    as JSON text in the result content.
    """
    if hasattr(result, "content"):
        for item in result.content:
            if hasattr(item, "text"):
                try:
                    data = json.loads(item.text)
                    if isinstance(data, list):
                        return [
                            entry["name"]
                            for entry in data
                            if isinstance(entry, dict) and "name" in entry
                        ]
                except (json.JSONDecodeError, KeyError):
                    pass
    return []


def get_available_tools_from_text(result: object) -> list[str]:
    """Get all tool names from a list_tools-like search with empty query."""
    return parse_tool_names(result)


async def evaluate_queries(
    proxy_url: str,
    queries: list[dict[str, list[str]]],
    scope_name: str,
) -> ScopeReport:
    """Run all queries against the proxy and evaluate results."""
    from fastmcp import Client

    report = ScopeReport(scope=scope_name, total_queries=len(queries))

    async with Client(proxy_url) as client:
        # First, discover which tools are in scope by doing a broad search
        all_tool_names: set[str] = set()
        for letter in "abcdefghijklmnopqrstuvwxyz_":
            result = await client.call_tool("search_tools", {"query": letter})
            names = parse_tool_names(result)
            all_tool_names.update(names)

        print(f"  Tools in scope: {len(all_tool_names)}")

        for q in queries:
            query = q["query"]
            expected = q["expected"]

            # Check if expected tools are blocked by scope
            expected_in_scope = [t for t in expected if t in all_tool_names]
            if not expected_in_scope:
                qr = QueryResult(
                    query=query,
                    expected=expected,
                    returned=[],
                    scope_blocked=True,
                )
                report.results.append(qr)
                report.scope_blocked += 1
                continue

            report.applicable_queries += 1

            result = await client.call_tool("search_tools", {"query": query})
            returned = parse_tool_names(result)

            hit = any(t in returned for t in expected_in_scope)
            p1 = bool(returned and returned[0] in expected_in_scope)
            p3 = any(t in expected_in_scope for t in returned[:3])

            qr = QueryResult(
                query=query,
                expected=expected,
                returned=returned,
                hit=hit,
                precision_at_1=p1,
                precision_at_3=p3,
            )

            if hit:
                report.hits += 1
            else:
                qr.miss_reason = analyze_miss(query, expected_in_scope, returned)
                report.misses.append(qr)

            if p1:
                report.p1_hits += 1
            if p3:
                report.p3_hits += 1

            report.results.append(qr)

    return report


def analyze_miss(
    query: str,
    expected: list[str],
    returned: list[str],
) -> str:
    """Generate a human-readable explanation for a miss."""
    keywords = query.lower().split()
    for tool in expected:
        has_overlap = any(kw in tool.lower() for kw in keywords)
        if not has_overlap:
            return f'keyword(s) {keywords} not in tool name "{tool}"'
    if returned:
        return f"returned {returned[:3]} instead of {expected}"
    return "no results returned"


def print_report(report: ScopeReport) -> None:
    """Print a formatted report for one scope."""
    n = report.applicable_queries
    print(f"\n=== Search Quality ({report.scope} scope, {report.total_queries} queries) ===\n")

    if report.scope_blocked:
        print(f"Scope-blocked queries (correctly hidden): {report.scope_blocked}")
    print(f"Applicable queries: {n}\n")

    print(f"Hit Rate:      {report.hits}/{n} ({report.hit_rate:.0f}%)")
    print(f"Precision@1:   {report.p1_hits}/{n} ({report.precision_at_1:.0f}%)")
    print(f"Precision@3:   {report.p3_hits}/{n} ({report.precision_at_3:.0f}%)")

    if report.misses:
        print(f"\nMisses ({len(report.misses)}):")
        for m in report.misses:
            returned_str = m.returned[:5] if m.returned else "[]"
            print(
                f'  "{m.query}" -> returned: {returned_str} '
                f"(expected: {m.expected}) -- {m.miss_reason}"
            )
    print()


def write_csv(reports: list[ScopeReport]) -> Path:
    """Write results to CSV file."""
    csv_path = RESULTS_DIR / "search_quality.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "scope",
                "total_queries",
                "applicable",
                "scope_blocked",
                "hit_rate_pct",
                "precision_at_1_pct",
                "precision_at_3_pct",
            ]
        )
        for r in reports:
            writer.writerow(
                [
                    r.scope,
                    r.total_queries,
                    r.applicable_queries,
                    r.scope_blocked,
                    round(r.hit_rate, 1),
                    round(r.precision_at_1, 1),
                    round(r.precision_at_3, 1),
                ]
            )
    return csv_path


def check_pass_criteria(report: ScopeReport) -> bool:
    """Check if hit rate > 75%."""
    passed = report.hit_rate > 75
    status = "PASS" if passed else "FAIL"
    print(f"Pass criteria: hit rate > 75% ({report.scope} scope)")
    print(f"  Actual: {report.hit_rate:.0f}% — {status}")
    return passed


async def run_experiment(proxy_url: str) -> list[ScopeReport]:
    """Run the search quality experiment."""
    queries_path = RESULTS_DIR / "queries.json"
    with open(queries_path) as f:
        queries = json.load(f)

    print("\n=== Experiment 3: Search Quality ===")
    print(f"  Proxy: {proxy_url}")
    print(f"  Queries: {len(queries)}\n")

    print("Evaluating queries...")
    report = await evaluate_queries(proxy_url, queries, "current")

    return [report]


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Experiment 3: Search Quality",
    )
    parser.add_argument(
        "--proxy-url",
        default=DEFAULT_PROXY_URL,
        help=f"URL of the mcp-guardian proxy (default: {DEFAULT_PROXY_URL})",
    )
    args = parser.parse_args()

    reports = asyncio.run(run_experiment(args.proxy_url))

    for report in reports:
        print_report(report)

    csv_path = write_csv(reports)
    print(f"Results saved to {csv_path}")

    passed = check_pass_criteria(reports[0])
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
