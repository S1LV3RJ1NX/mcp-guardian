# Comparison

How mcp-guardian compares to other approaches for managing MCP tool sprawl.

## vs Direct Connection

**Direct connection** is the default: your MCP client connects straight to each upstream server and loads all tool schemas into context.

| Factor | Direct | mcp-guardian |
|--------|--------|-------------|
| Setup | Zero config | Requires scope.yaml |
| Token cost | All schemas upfront (160K+ tokens) | 3 meta-tool schemas (456 tokens) |
| Tool scoping | None — client sees everything | Per-scope allowlist/blocklist |
| Audit logging | None | JSONL audit trail |
| Auth management | Per-client | Centralized in proxy (env, dashboard, or OAuth) |
| Credential UX | Distribute tokens to each client | Web dashboard for OAuth connect + API key entry |
| Latency overhead | None | Negligible (-8ms in benchmarks) |

**When direct is fine:**
- Single server with <30 tools
- No need for scoping or audit
- Prototype or personal use

**When mcp-guardian wins:**
- Multiple servers with 39+ tools combined
- Need role-based tool access (support agent vs developer)
- Need audit trail for compliance
- Need centralized auth — manage OAuth sessions and API keys from a web dashboard instead of distributing tokens per client

## vs FastMCP Code Mode

[FastMCP Code Mode](https://gofastmcp.com) lets you programmatically compose MCP servers in Python — importing tools from other servers, filtering, transforming, and re-exporting them.

| Factor | FastMCP Code Mode | mcp-guardian |
|--------|-------------------|-------------|
| Approach | Code-defined server composition | Config-driven proxy |
| Requires server code changes | Yes (Python composition) | No (works with any MCP server) |
| Token savings | Partial (re-exports filtered tools) | Full (3 meta-tools regardless) |
| Scoping | Programmatic (Python code) | Declarative (YAML) |
| Search/discovery | Not built-in | Built-in keyword search |
| Audit | Not built-in | Built-in JSONL logging |

**When Code Mode is better:**
- You own the server code
- You want to transform tool schemas (rename, merge, add validation)
- You want maximum control over composition logic

**When mcp-guardian is better:**
- You're proxying third-party servers you don't control
- You want config-driven scoping without writing code
- You want progressive discovery (search → schema → execute)

**They're complementary:** You can use Code Mode to build a custom upstream server, then put mcp-guardian in front for scoping and progressive discovery.

## vs MCP Spec Recommendation

The [MCP specification's Client Best Practices](https://modelcontextprotocol.io/docs/develop/clients/client-best-practices) recommends that clients implement progressive tool discovery:

> "Implement progressive disclosure where tools are made available based on context"

mcp-guardian implements this recommendation at the infrastructure layer instead of the client layer. The advantage: every MCP client gets progressive discovery automatically, without client-side changes.

| Factor | Client-side implementation | mcp-guardian |
|--------|--------------------------|-------------|
| Who changes | Each client individually | One proxy for all clients |
| Works with closed-source clients | No | Yes |
| Consistent across clients | No (each implements differently) | Yes (one proxy, one behavior) |
| Scoping | Client must implement | Proxy handles it |
| OAuth / credential management | Client must implement per-server | Proxy manages sessions centrally, dashboard for interactive auth |
