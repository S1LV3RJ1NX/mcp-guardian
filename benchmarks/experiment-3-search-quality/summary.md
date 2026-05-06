# Experiment 3: Search Quality

## Setup

| Parameter | Value |
|-----------|-------|
| Test queries | 20 (from `queries.json`) |
| Search strategy | Keyword-based (exact name > name contains > description contains) |
| Upstream servers | PostgreSQL MCP (248 tools), GitHub MCP (41 tools) |

Tested against two scopes:
- **developer** — full access minus destructive ops (282 tools in scope)
- **support-agent** — read-only subset (14 tools in scope)

## Results: Developer Scope

| Metric | Value |
|--------|------:|
| Total queries | 20 |
| Scope-blocked (correctly hidden) | 5 |
| Applicable queries | 15 |
| **Hit rate** | **14/15 (93%)** |
| Precision@1 | 8/15 (53%) |
| Precision@3 | 12/15 (80%) |

### Misses (1)

| Query | Expected | Returned | Reason |
|-------|----------|----------|--------|
| "open bugs" | `list_issues` | [] | Keywords "open" and "bugs" have no overlap with tool name "list_issues" |

## Results: Support-Agent Scope

| Metric | Value |
|--------|------:|
| Total queries | 20 |
| Scope-blocked (correctly hidden) | 11 |
| Applicable queries | 9 |
| **Hit rate** | **8/9 (89%)** |
| Precision@1 | 8/9 (89%) |
| Precision@3 | 8/9 (89%) |

### Misses (1)

Same miss as developer scope: "open bugs" has no keyword overlap with "list_issues".

## Key Findings

1. **Keyword search achieves 93% hit rate** on the developer scope (282 tools) — well above the 75% threshold.

2. **The only miss is "open bugs" → `list_issues`** — a synonym gap. The word "bugs" doesn't appear in the tool name "list_issues" or its description. This is the classic limitation of keyword search.

3. **Precision@1 is 53%** (developer scope) — the first result is the expected tool about half the time. This is acceptable for a progressive discovery pattern where the LLM reviews a short list.

4. **Precision@3 is 80%** — in 4 out of 5 queries, the expected tool appears in the top 3 results. This means a 3-result preview would be sufficient for most use cases.

5. **Scope blocking works correctly** — 5 queries (developer) and 11 queries (support-agent) were correctly excluded because the expected tools are not in scope.

## Implications for Future Improvement

The single miss ("open bugs" → `list_issues`) demonstrates the value of upgrading to fuzzy or semantic search:

- **Fuzzy matching** (e.g., Levenshtein distance) would help with typos but not synonyms
- **Semantic search** (embedding-based) would correctly map "bugs" → "issues"
- **Alias mapping** (simple dict: `{"bugs": "issues", "PR": "pull_request"}`) would be a lightweight fix

These improvements are documented in `AGENTS.md` as future enhancements.

## Pass Criteria

> Hit rate > 75% on the developer scope

**Result: PASS** — 93% hit rate far exceeds the 75% threshold.

## Reproduction

```bash
# Start proxy with developer scope
uv run python -m mcp_guardian --config scope.yaml --scope developer

# Run benchmark
uv run python benchmarks/experiment-3-search-quality/bench_search_quality.py
```
