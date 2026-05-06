"""Experiment 4: Scaling — Token Savings vs Tool Count.

Generates synthetic tool schemas at various scale points and measures
direct vs proxy token cost. No live servers needed — runs entirely
in-process.

Usage:
  uv run python benchmarks/experiment-4-scaling/bench_scaling.py
"""

from __future__ import annotations

import csv
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent / "src"))

from mcp_guardian.tokens import build_meta_tools_token_count, count_tokens  # noqa: E402

RESULTS_DIR = Path(__file__).parent
SCALE_POINTS = [14, 30, 50, 100, 200, 500]

ACTIONS = [
    "create",
    "list",
    "get",
    "update",
    "delete",
    "search",
    "count",
    "export",
    "import",
    "validate",
    "analyze",
    "sync",
    "archive",
    "restore",
    "merge",
    "split",
    "transform",
    "filter",
]
RESOURCES = [
    "report",
    "user",
    "account",
    "invoice",
    "ticket",
    "project",
    "task",
    "comment",
    "event",
    "metric",
    "alert",
    "config",
    "session",
    "workflow",
    "pipeline",
    "dataset",
    "schema",
    "record",
]
PARAM_TYPES = ["string", "integer", "boolean", "number"]
PARAM_NAMES = [
    "id",
    "name",
    "filter",
    "limit",
    "offset",
    "sort_by",
    "status",
    "start_date",
    "end_date",
    "format",
    "verbose",
    "include_metadata",
    "tags",
    "owner",
    "priority",
    "category",
]


def generate_tools(n: int, seed: int = 42) -> list[dict]:
    """Generate n realistic tool schemas with deterministic randomness."""
    rng = random.Random(seed)
    tools = []

    for i in range(n):
        action = ACTIONS[i % len(ACTIONS)]
        resource = RESOURCES[i % len(RESOURCES)]
        name = f"{action}_{resource}_{i:03d}"

        num_params = rng.randint(1, 5)
        params = {}
        chosen_params = rng.sample(PARAM_NAMES, min(num_params, len(PARAM_NAMES)))
        for pname in chosen_params:
            params[pname] = {
                "type": rng.choice(PARAM_TYPES),
                "description": f"The {pname} parameter for {action} {resource}",
            }

        tool = {
            "name": name,
            "description": (
                f"{action.replace('_', ' ').title()} {resource}s. "
                f"Performs {action} operation on the {resource} resource "
                f"with {num_params} configurable parameters."
            ),
            "inputSchema": {
                "type": "object",
                "properties": params,
                "required": list(params.keys())[: rng.randint(1, len(params))],
            },
        }
        tools.append(tool)

    return tools


def measure_direct_tokens(tools: list[dict]) -> int:
    """Sum token cost of all tool schemas."""
    total = 0
    for tool in tools:
        total += count_tokens(json.dumps(tool, separators=(",", ":")))
    return total


def run_experiment() -> list[dict]:
    """Run scaling experiment across all scale points."""
    proxy_tokens = build_meta_tools_token_count()

    print("\n=== Experiment 4: Scaling — Token Savings vs Tool Count ===\n")
    print(f"Proxy tokens (fixed): {proxy_tokens}\n")

    header = (
        f"{'Tools':>6}  {'Direct Tokens':>14}  {'Proxy Tokens':>13}  "
        f"{'Savings %':>10}  {'Tokens/Tool':>12}  {'Verdict'}"
    )
    print(header)
    print("-" * len(header))

    results = []
    for n in SCALE_POINTS:
        tools = generate_tools(n)
        direct = measure_direct_tokens(tools)
        savings_pct = (1 - proxy_tokens / direct) * 100 if direct > 0 else 0
        per_tool = direct / n

        if savings_pct > 99:
            verdict = "Proxy wins dramatically"
        elif savings_pct > 97:
            verdict = "Proxy wins clearly"
        elif savings_pct > 95:
            verdict = "Proxy wins"
        else:
            verdict = "Marginal"

        print(
            f"{n:>6}  {direct:>14,}  {proxy_tokens:>13,}  "
            f"{savings_pct:>9.1f}%  {per_tool:>11.0f}  {verdict}"
        )

        results.append(
            {
                "tools": n,
                "direct_tokens": direct,
                "proxy_tokens": proxy_tokens,
                "savings_pct": round(savings_pct, 1),
                "tokens_per_tool": round(per_tool, 1),
            }
        )

    print()
    return results


def find_breakeven(proxy_tokens: int) -> int:
    """Find the minimum tool count where savings first exceed 95%."""
    for n in range(1, 1000):
        tools = generate_tools(n)
        direct = measure_direct_tokens(tools)
        if direct > 0 and (1 - proxy_tokens / direct) * 100 > 95:
            return n
    return -1


def write_csv(results: list[dict]) -> Path:
    """Write results to CSV file."""
    csv_path = RESULTS_DIR / "scaling.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "tools",
                "direct_tokens",
                "proxy_tokens",
                "savings_pct",
                "tokens_per_tool",
            ]
        )
        for r in results:
            writer.writerow(
                [
                    r["tools"],
                    r["direct_tokens"],
                    r["proxy_tokens"],
                    r["savings_pct"],
                    r["tokens_per_tool"],
                ]
            )
    return csv_path


def check_pass_criteria(results: list[dict]) -> bool:
    """Check if savings > 95% at all scale points."""
    all_pass = all(r["savings_pct"] > 95 for r in results)
    min_savings = min(r["savings_pct"] for r in results)
    status = "PASS" if all_pass else "FAIL"
    print("Pass criteria: savings > 95% at all scale points")
    print(f"  Minimum savings: {min_savings}% — {status}")
    return all_pass


def main() -> None:
    """Entry point."""
    results = run_experiment()

    proxy_tokens = build_meta_tools_token_count()
    breakeven = find_breakeven(proxy_tokens)
    print(f"Break-even point (95% savings): {breakeven} tools\n")

    csv_path = write_csv(results)
    print(f"Results saved to {csv_path}")
    passed = check_pass_criteria(results)

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
