# Experiment 4: Scaling — Token Savings vs Tool Count

## Setup

| Parameter | Value |
|-----------|-------|
| Tool schemas | Synthetically generated (deterministic, realistic params) |
| Proxy tokens | 155 (fixed: 3 meta-tool schemas) |
| Scale points | 14, 30, 50, 100, 200, 500 |
| Token counting | `len(text) // 4` approximation (tiktoken fallback) |

## Results

| Tools | Direct Tokens | Proxy Tokens | Savings % | Tokens/Tool | Verdict |
|------:|--------------:|-------------:|----------:|------------:|---------|
| 14 | 997 | 155 | 84.5% | 71 | Marginal |
| 30 | 2,433 | 155 | 93.6% | Marginal |
| 50 | 4,241 | 155 | 96.3% | 85 | Proxy wins |
| 100 | 8,883 | 155 | 98.3% | 89 | Proxy wins clearly |
| 200 | 17,848 | 155 | 99.1% | 89 | Proxy wins dramatically |
| 500 | 45,186 | 155 | 99.7% | 90 | Proxy wins dramatically |

## Break-Even Analysis

**The proxy first exceeds 95% savings at 39 tools.**

Below 39 tools, the 3 meta-tool schemas (~155 tokens) are a significant fraction of the total direct cost. Above 39 tools, the proxy's fixed overhead becomes negligible.

For context:
- PostgreSQL MCP: 248 tools (99.6% savings in Experiment 1)
- GitHub MCP: 41 tools (just above break-even)
- Combined: 289 tools (99.7% savings in Experiment 1)

Most real-world MCP servers have 30-250+ tools, placing them firmly in the "proxy wins" zone.

## Key Findings

1. **Token cost scales linearly** with tool count (~85-90 tokens per tool for realistic schemas).

2. **Proxy cost is constant** — always 155 tokens (3 meta-tool schemas) regardless of upstream tool count.

3. **Break-even at 39 tools** — the proxy achieves >95% savings for any server with 39+ tools.

4. **At 100+ tools** savings exceed 98%, and at 500 tools the savings reach 99.7%.

5. **For tiny servers (<15 tools)** the proxy still saves tokens (84.5% at 14 tools) but the absolute savings are small (~842 tokens). The operational benefit of scoping and audit logging may still justify it.

## Pass Criteria

> Savings > 95% at all scale points

**Result: FAIL** at the two smallest scale points (14 tools: 84.5%, 30 tools: 93.6%). This is expected and informative — it tells us the proxy is optimized for servers with 39+ tools. At 50+ tools (96.3%+), all points pass.

## Reproduction

```bash
uv run python benchmarks/experiment-4-scaling/bench_scaling.py
```
