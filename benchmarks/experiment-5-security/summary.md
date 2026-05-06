# Experiment 5: Scope Security Validation

## Setup

| Parameter | Value |
|-----------|-------|
| Scope | `support-agent` (explicit allowlist: 14 tools) |
| Blocked tools tested | 9 (4 GitHub + 5 PostgreSQL) |
| Attack vectors | 3 per tool (search, get_schema, execute) |
| Total checks | 27 |

## Blocked Tools Tested

**GitHub** (not in support-agent allowlist):
- `delete_file`
- `fork_repository`
- `push_files`
- `create_repository`

**PostgreSQL** (not in support-agent allowlist):
- `pg_drop_table`
- `pg_truncate`
- `pg_write_query`
- `pg_vacuum`
- `pg_terminate_backend`

## Results

| Blocked Tool | search_tools | get_schema | execute_tool |
|--------------|:------------:|:----------:|:------------:|
| delete_file | HIDDEN | BLOCKED | BLOCKED |
| fork_repository | HIDDEN | BLOCKED | BLOCKED |
| push_files | HIDDEN | BLOCKED | BLOCKED |
| create_repository | HIDDEN | BLOCKED | BLOCKED |
| pg_drop_table | HIDDEN | BLOCKED | BLOCKED |
| pg_truncate | HIDDEN | BLOCKED | BLOCKED |
| pg_write_query | HIDDEN | BLOCKED | BLOCKED |
| pg_vacuum | HIDDEN | BLOCKED | BLOCKED |
| pg_terminate_backend | HIDDEN | BLOCKED | BLOCKED |

**27/27 checks passed.**

## Three-Vector Security Model

The proxy enforces scope at three independent layers:

1. **search_tools** -- blocked tools never appear in search results, so the LLM cannot discover them
2. **get_schema** -- requesting schema for a blocked tool returns an error, preventing parameter discovery
3. **execute_tool** -- even if a tool name is guessed directly (bypassing search), execution returns `TOOL_NOT_IN_SCOPE`

This defense-in-depth means a blocked tool cannot be accessed even if an attacker knows the exact tool name.

## Key Finding

**Scope enforcement is airtight.** All 9 blocked tools are completely invisible across all three meta-tools. There are no bypass vectors — a `support-agent` session cannot discover, inspect, or execute any tool outside its allowlist.

## Pass Criteria

> 100% of blocked tools invisible (any failure is a security bug)

**Result: PASS** -- 27/27 checks passed.

## Reproduction

```bash
# Start proxy with support-agent scope
uv run python -m mcp_guardian --config scope.yaml --scope support-agent

# Run security validation
uv run python benchmarks/experiment-5-security/bench_security.py
```
