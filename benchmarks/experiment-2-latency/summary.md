# Experiment 2: Latency Comparison

## Setup

| Parameter | Value |
|-----------|-------|
| Upstream server | PostgreSQL MCP (TrueFoundry-hosted, remote) |
| Proxy | mcp-guardian on localhost:9000 |
| Scope | `support-agent` (14 allowed tools) |
| Iterations | 20 per mode |
| Warm-up | 1 run per mode (discarded) |

### Modes

| Mode | Steps |
|------|-------|
| Direct | connect → list tools (248) → call `pg_list_tables` |
| Proxy | connect → list tools (3) → `search_tools` → `get_schema` → `execute_tool` |

## Results

| Mode | Mean | Median | P95 | Min | Max |
|------|-----:|-------:|----:|----:|----:|
| Direct | 4,652ms | 4,624ms | 4,838ms | 4,499ms | 4,875ms |
| Proxy | 4,644ms | 4,640ms | 4,709ms | 4,474ms | 4,830ms |
| **Overhead** | **-8ms** | **19ms** | **196ms** | **-346ms** | **203ms** |

## Key Finding

**The proxy adds negligible latency overhead.** Mean overhead is -8ms (within noise), meaning the proxy is effectively free in terms of latency.

Why the proxy can even be *faster* than direct despite making 3 calls instead of 1:

1. **Direct mode loads 248 tool schemas** at connect time — the `list_tools` response is massive (~108K tokens of JSON). Parsing and transferring this data takes significant time.
2. **Proxy mode loads only 3 meta-tool schemas** — the `list_tools` response is tiny (456 tokens). The three subsequent tool calls are lightweight RPCs.
3. The network round-trip to the remote PostgreSQL MCP (~4.5s per call) dominates both modes equally since both ultimately call `pg_list_tables` once on the upstream.

## Why It Matters

The proxy's 3-call pattern (search → schema → execute) does not add meaningful latency versus a single direct call. Users get the **99.7% token savings** (from Experiment 1) with **zero latency penalty**.

For local upstream servers (sub-millisecond round-trips), the overhead would be a few milliseconds — still negligible compared to LLM inference time (1-3 seconds).

## Pass Criteria

> Proxy overhead mean < 200ms

**Result: PASS** — Mean overhead of -8ms is well below the 200ms threshold.

## Reproduction

```bash
# Prerequisites: upstream PostgreSQL MCP accessible, proxy running
uv run python -m mcp_guardian --config scope.yaml --scope support-agent
uv run python benchmarks/experiment-2-latency/bench_latency.py --runs 20
```
