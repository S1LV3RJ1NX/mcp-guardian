# Experiment 1: Token Cost Comparison

## Setup

| Server | Tools | Transport |
|--------|------:|-----------|
| PostgreSQL MCP (TrueFoundry-hosted) | 248 | Streamable HTTP |
| GitHub MCP (api.githubcopilot.com) | 41 | Streamable HTTP |
| **Total upstream** | **289** | |

**Proxy scope:** `support-agent` (14 allowed tools: 7 postgres + 7 github)

Token counting: `tiktoken` with `cl100k_base` encoding (falls back to `len(text) // 4` approximation if tiktoken unavailable).

## Results

| Mode | Tokens | Savings vs Direct |
|------|-------:|------------------:|
| **Direct** (all 289 tool schemas) | 160,143 | — (baseline) |
| **Proxy startup** (3 meta-tools) | 456 | **99.7%** |
| **Proxy after search** (startup + search result) | 505 | 99.7% |
| **Proxy after schema** (startup + search + 1 full schema) | 2,119 | 98.7% |

### Postgres-only run (no GitHub)

| Mode | Tokens | Savings vs Direct |
|------|-------:|------------------:|
| Direct (248 tools) | 108,549 | — |
| Proxy startup | 456 | 99.6% |
| Proxy after search | 505 | 99.5% |
| Proxy after schema | 2,119 | 98.0% |

## Key Finding

**mcp-guardian reduces session-startup token cost by 99.7%** — from 160,143 tokens (loading all 289 upstream tool schemas) down to 456 tokens (3 meta-tool schemas).

Even after a full search-then-drill-down workflow (search + get_schema for one tool), the cumulative cost is only 2,119 tokens — still a **98.7% reduction** versus the direct approach.

## Why It Matters

At GPT-4o input pricing ($2.50 / 1M tokens):

| Mode | Cost per session | Annual cost (1000 sessions/day) |
|------|----------------:|-----------:|
| Direct | $0.000400 | $146.13 |
| Proxy startup | $0.000001 | $0.42 |
| Savings | $0.000399 | **$145.71/yr** |

The token savings translate directly to lower latency (fewer tokens to process in the context window) and reduced cost at scale.

## Pass Criteria

> Proxy startup savings > 95%

**Result: PASS** — 99.7% savings at startup far exceeds the 95% threshold.

## Reproduction

```bash
# Prerequisites: upstream servers accessible, proxy running
uv run python -m mcp_guardian --config scope.yaml --scope support-agent
uv run python benchmarks/experiment-1-token-cost/bench_tokens.py
```
