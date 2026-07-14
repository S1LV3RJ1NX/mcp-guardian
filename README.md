# mcp-guardian

> Talk: **"Putting MCP on a Diet: A Proxy for Tool Scoping and Context Compression"** at [MCP Dev Summit Bengaluru](https://events.linuxfoundation.org/mcp-dev-summit-bengaluru/) · 9-10 June 2026

A transparent MCP proxy for progressive tool discovery and tool scoping — the tool-exposure layer of your agent harness. It sits between your AI client and upstream MCP servers, replacing hundreds of tool schemas with three meta-tools (`search_tools`, `get_schema`, `execute_tool`). This implements the [MCP spec's progressive discovery recommendation](https://modelcontextprotocol.io/docs/develop/clients/client-best-practices) at the infrastructure layer — no client changes needed.

## Why

When an MCP client connects directly to servers with 200+ tools, every tool schema is loaded into the LLM context window at startup. That's 160,000+ tokens before the first message. mcp-guardian replaces that with 3 tool schemas (456 tokens) — a **99.7% reduction**.

## Architecture

```
┌──────────────┐         ┌──────────────────────┐         ┌──────────────┐
│              │         │    mcp-guardian       │         │ PostgreSQL   │
│   AI Client  │◄───────►│                      │◄───────►│ MCP (248     │
│  (Claude,    │   3     │  scope.yaml defines:  │         │ tools)       │
│   Cursor,    │  meta   │  - allowed/blocked    │         └──────────────┘
│   etc.)      │ tools   │    tools per scope    │
│              │         │  - auth per server    │         ┌──────────────┐
└──────────────┘         │  - audit logging      │◄───────►│ GitHub MCP   │
                         │                      │         │ (41 tools)   │
                         └──────────────────────┘         └──────────────┘
```

The client sees only three tools:

1. **`search_tools(query)`** — pluggable search (keyword, semantic, …) over allowed tools, returns names + brief descriptions
2. **`get_schema(tool_name)`** — full parameter schema for one tool
3. **`execute_tool(tool_name, params)`** — proxied call to the upstream server

## Quick Start

```bash
# 1. Clone and install
git clone https://github.com/prathamesh-saraf/mcp-guardian.git
cd mcp-guardian
uv sync --dev

# 2. Configure
cp examples/scope.direct.yaml scope.yaml
cp .env.example .env
# Edit .env with your POSTGRES_MCP_URL (and optionally GITHUB_OAUTH_SECRET, TRENDS_API_KEY)

# 3. Run
uv run mcp-guardian --scope support-agent

# 4. Open the dashboard at http://localhost:9000/
#    Connect MCP clients to http://localhost:9000/mcp
```

The proxy serves a **web dashboard** at the root URL for managing server connections, browsing tools, entering API keys, triggering OAuth flows, and a **Chat Demo** tab that lets you converse with your tools via an LLM while comparing token costs with and without the proxy.

See [docs/QUICKSTART.md](docs/QUICKSTART.md) for a detailed walkthrough.

## Configuration

### scope.yaml

```yaml
upstream_servers:
  github:
    url: https://api.githubcopilot.com/mcp/
    auth:
      type: oauth
      client_id: Iv23li...                # pre-registered OAuth app
      client_secret_env: GITHUB_OAUTH_SECRET

  postgres:
    url_env: POSTGRES_MCP_URL             # URL from env var
    auth:
      type: none

  trends:
    url: https://x-twitter.api.trendsmcp.ai/mcp
    auth:
      type: bearer_env
      value_env: TRENDS_API_KEY           # or enter via dashboard

scopes:
  support-agent:                          # Read-only scope
    servers:
      github:
        allowed_tools:
          - get_me
          - list_issues
          - search_issues
      postgres:
        allowed_tools:
          - pg_read_query
          - pg_list_tables
          - pg_describe_table
      trends:
        allowed_tools:
          - trendsMCP___get_top_trends

  developer:                              # Broad scope with blocklist
    servers:
      github:
        allowed_tools: "*"
        blocked_tools: [delete_file, push_files]
      postgres:
        allowed_tools: "*"
        blocked_tools: [pg_drop_table, pg_truncate]
      trends:
        allowed_tools: "*"

audit:
  enabled: true
  log_file: audit.log
  include_params: true
```

See [docs/WRITING_SCOPE_YAML.md](docs/WRITING_SCOPE_YAML.md) for the full reference.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GUARDIAN_HOST` | `0.0.0.0` | Bind address |
| `GUARDIAN_PORT` | `9000` | Listen port |
| `GUARDIAN_CONFIG_PATH` | `scope.yaml` | Path to config file |
| `GUARDIAN_SCOPE` | (required) | Active scope name |
| `GUARDIAN_LOG_LEVEL` | `INFO` | Log level |
| `GUARDIAN_LLM_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible API base URL (for Chat Demo) |
| `GUARDIAN_LLM_API_KEY` | *(empty)* | LLM API key (for Chat Demo) |
| `GUARDIAN_LLM_MODEL_NAME` | `gpt-4o-mini` | Model name (for Chat Demo) |

Auth tokens are referenced by name in `scope.yaml` and resolved from `.env`, the dashboard, or client headers.

### Auth Types

| Type | Description |
|------|-------------|
| `none` | No authentication |
| `bearer_env` | Bearer token resolved from: client header > dashboard KeyStore > env var (`value_env`) |
| `static_header` | Custom header from env var (`header`, `value_env`) |
| `token_passthrough` | Forward client's Authorization header to upstream |
| `oauth` | Browser-based OAuth flow. Optional `client_id` / `client_secret_env` for pre-registered apps |

## Benchmark Results

Tested against real upstream servers: PostgreSQL MCP (248 tools) + GitHub MCP (41 tools).

| Experiment | Key Metric | Result | Status |
|-----------|------------|--------|:------:|
| Token Cost | Startup savings | 99.7% (160,143 → 456 tokens) | PASS |
| Latency | Proxy overhead | -8ms mean (within noise) | PASS |
| Search Quality | Hit rate | 93% (keyword search) | PASS |
| Scaling | Break-even | 39 tools for >95% savings | PASS* |
| Security | Scope enforcement | 27/27 checks passed | PASS |

*Savings exceed 95% for servers with 39+ tools. See [benchmarks/summary.md](benchmarks/summary.md) for details.

## Docker

```bash
# Build
docker build -t mcp-guardian .

# Run
docker run -p 9000:9000 \
  -v ./scope.yaml:/app/scope.yaml \
  -e GUARDIAN_SCOPE=support-agent \
  -e GITHUB_TOKEN=ghp_your_token \
  -e POSTGRES_MCP_URL=https://your-pg-mcp.example.com/mcp \
  mcp-guardian
```

Or use docker-compose for a full dev environment:

```bash
docker compose up --build
```

See [docker-compose.yml](docker-compose.yml) for the full setup.

## Comparison

| Approach | When to use |
|----------|------------|
| **Direct connection** | Few tools (<30), single server, no scoping needed |
| **mcp-guardian proxy** | Many tools (39+), multiple servers, need scoping/audit |
| **FastMCP Code Mode** | You own the server code and want to filter programmatically |

mcp-guardian and FastMCP Code Mode are complementary — the proxy works with any MCP server without code changes.

See [docs/COMPARISON.md](docs/COMPARISON.md) for a detailed comparison.

## Known Gotchas

- **URL paths:** Most MCP servers serve at `/mcp` (e.g., `http://localhost:3000/mcp`). Don't forget the path suffix.
- **Transport:** The proxy defaults to `streamable-http`. Use `--transport sse` or `--transport stdio` if your client requires it.
- **tiktoken:** Token counting uses tiktoken which downloads encoding data on first use. In air-gapped environments it falls back to a character-based approximation.
- **OAuth tokens are in-memory:** OAuth sessions are lost on restart. The dashboard shows "Pending OAuth" and you click Connect again. API keys entered via dashboard are restored from browser localStorage automatically.
- **Graceful shutdown:** Press `Ctrl+C` to stop the proxy. It cleanly closes all OAuth client sessions before exiting.

## Development

```bash
# Install dev dependencies
uv sync --dev

# Install pre-commit hooks
uv run pre-commit install

# Run tests
uv run pytest tests/ -v

# Lint
uv run ruff check src/ tests/
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines.

## License

MIT — see [LICENSE](LICENSE).
