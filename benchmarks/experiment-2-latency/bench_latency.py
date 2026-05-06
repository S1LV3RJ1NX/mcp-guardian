"""Experiment 2: Latency Comparison.

Measures wall-clock time overhead of the proxy vs direct connections
across multiple runs.

Modes:
  1. Direct — connect to PostgreSQL MCP, call pg_list_tables directly
  2. Proxy  — connect to proxy, search_tools → get_schema → execute_tool

Prerequisites:
  - PostgreSQL MCP server running
  - mcp-guardian proxy running: uv run mcp-guardian --scope support-agent

Usage:
  uv run python benchmarks/experiment-2-latency/bench_latency.py
  uv run python benchmarks/experiment-2-latency/bench_latency.py --runs 50
  uv run python benchmarks/experiment-2-latency/bench_latency.py --proxy-url http://localhost:9000/mcp
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import math
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent / "src"))

RESULTS_DIR = Path(__file__).parent
DEFAULT_PROXY_URL = "http://localhost:9000/mcp"


def stats(times_ms: list[float]) -> dict[str, float]:
    """Compute mean, median, p95, min, max from a list of times."""
    s = sorted(times_ms)
    n = len(s)
    mean = sum(s) / n
    median = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
    p95_idx = min(math.ceil(n * 0.95) - 1, n - 1)
    return {
        "mean": round(mean, 1),
        "median": round(median, 1),
        "p95": round(s[p95_idx], 1),
        "min": round(s[0], 1),
        "max": round(s[-1], 1),
    }


async def run_direct_once(postgres_url: str) -> float:
    """Single direct run: connect → list tools → call pg_list_tables.

    Returns elapsed time in milliseconds.
    """
    from fastmcp import Client

    t0 = time.perf_counter()
    async with Client(postgres_url) as client:
        await client.list_tools()
        await client.call_tool("pg_list_tables", {})
    return (time.perf_counter() - t0) * 1000


async def run_proxy_once(proxy_url: str) -> float:
    """Single proxy run: connect → list tools → search → get_schema → execute.

    Returns elapsed time in milliseconds.
    """
    from fastmcp import Client

    t0 = time.perf_counter()
    async with Client(proxy_url) as client:
        await client.list_tools()
        await client.call_tool("search_tools", {"query": "tables"})
        await client.call_tool("get_schema", {"tool_name": "pg_list_tables"})
        await client.call_tool(
            "execute_tool",
            {"tool_name": "pg_list_tables", "params": {}},
        )
    return (time.perf_counter() - t0) * 1000


async def run_experiment(
    proxy_url: str,
    num_runs: int,
) -> dict[str, dict[str, float]]:
    """Run both modes for num_runs iterations and return stats."""
    postgres_url = os.environ.get(
        "POSTGRES_MCP_URL",
        "http://localhost:3000/mcp",
    )

    print(f"\n=== Experiment 2: Latency Comparison ({num_runs} runs) ===\n")
    print(f"  PostgreSQL MCP: {postgres_url}")
    print(f"  Proxy:          {proxy_url}\n")

    # Warm-up run (not counted)
    print("Warm-up...")
    try:
        await run_direct_once(postgres_url)
    except Exception as exc:
        print(f"  WARNING: Direct warm-up failed: {exc}")
    try:
        await run_proxy_once(proxy_url)
    except Exception as exc:
        print(f"  WARNING: Proxy warm-up failed: {exc}")

    direct_times: list[float] = []
    proxy_times: list[float] = []

    print(f"\nRunning {num_runs} iterations...")
    for i in range(num_runs):
        d = await run_direct_once(postgres_url)
        direct_times.append(d)

        p = await run_proxy_once(proxy_url)
        proxy_times.append(p)

        sys.stdout.write(f"\r  {i + 1}/{num_runs}")
        sys.stdout.flush()

    print("\n")

    overhead_times = [p - d for p, d in zip(proxy_times, direct_times, strict=True)]

    return {
        "direct": stats(direct_times),
        "proxy": stats(proxy_times),
        "overhead": stats(overhead_times),
    }


def print_results(results: dict[str, dict[str, float]]) -> None:
    """Print a formatted results table."""
    header = f"{'Mode':<12} {'Mean':>8} {'Median':>8} {'P95':>8} {'Min':>8} {'Max':>8}"
    print(header)
    print("-" * len(header))
    for mode, s in results.items():
        print(
            f"{mode:<12} {s['mean']:>7.1f}ms {s['median']:>7.1f}ms "
            f"{s['p95']:>7.1f}ms {s['min']:>7.1f}ms {s['max']:>7.1f}ms"
        )
    print()


def write_csv(results: dict[str, dict[str, float]]) -> Path:
    """Write results to CSV file."""
    csv_path = RESULTS_DIR / "latency.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["mode", "mean_ms", "median_ms", "p95_ms", "min_ms", "max_ms"])
        for mode, s in results.items():
            writer.writerow([mode, s["mean"], s["median"], s["p95"], s["min"], s["max"]])
    return csv_path


def check_pass_criteria(results: dict[str, dict[str, float]]) -> bool:
    """Check if proxy overhead mean < 200ms."""
    overhead_mean = results["overhead"]["mean"]
    passed = overhead_mean < 200
    status = "PASS" if passed else "FAIL"
    print("Pass criteria: proxy overhead mean < 200ms")
    print(f"  Actual: {overhead_mean:.1f}ms — {status}")
    return passed


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Experiment 2: Latency Comparison",
    )
    parser.add_argument(
        "--proxy-url",
        default=DEFAULT_PROXY_URL,
        help=f"URL of the mcp-guardian proxy (default: {DEFAULT_PROXY_URL})",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=20,
        help="Number of iterations per mode (default: 20)",
    )
    args = parser.parse_args()

    results = asyncio.run(run_experiment(args.proxy_url, args.runs))
    print_results(results)
    csv_path = write_csv(results)
    print(f"Results saved to {csv_path}")
    passed = check_pass_criteria(results)

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
