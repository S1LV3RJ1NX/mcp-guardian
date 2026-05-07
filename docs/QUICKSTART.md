# Quick Start

Get mcp-guardian running in 5 minutes.

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager
- At least one upstream MCP server (PostgreSQL MCP or GitHub MCP)

## 1. Install

```bash
git clone https://github.com/prathamesh-saraf/mcp-guardian.git
cd mcp-guardian
uv sync --dev
```

## 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your values:

```bash
# Required: at least one upstream server
POSTGRES_MCP_URL=http://localhost:3000/mcp

# Optional: GitHub OAuth (or connect via dashboard)
GITHUB_OAUTH_SECRET=your_github_oauth_secret

# Optional: Trends API key (or enter via dashboard)
TRENDS_API_KEY=your_trends_key

# Proxy settings (defaults are fine for local dev)
GUARDIAN_SCOPE=support-agent

# Optional: LLM for the Chat Demo tab (any OpenAI-compatible endpoint)
GUARDIAN_LLM_BASE_URL=https://api.openai.com/v1
GUARDIAN_LLM_API_KEY=sk-...
GUARDIAN_LLM_MODEL_NAME=gpt-4o-mini
```

## 3. Configure Scope

```bash
cp examples/scope.direct.yaml scope.yaml
```

The example config defines three upstream servers and two scopes:
- `support-agent` — read-only tools (7 postgres + 7 github + 1 trends)
- `developer` — full access minus destructive operations

Edit `scope.yaml` to customize tool access per scope. See [WRITING_SCOPE_YAML.md](WRITING_SCOPE_YAML.md) for the full reference.

## 4. Start Upstream Servers

**PostgreSQL MCP** (via Docker):

```bash
docker run --rm -p 3000:3000 \
  -e POSTGRES_URL="postgresql://user:pass@host:5432/dbname" \
  writenotenow/postgres-mcp:latest \
  --transport http --port 3000
```

**GitHub MCP** — uses OAuth. The proxy will prompt for authorization via the dashboard when you click "Connect".

**Trends MCP** — uses an API key. Set `TRENDS_API_KEY` in `.env` or enter it in the dashboard.

## 5. Verify Upstream

```bash
uv run python scripts/verify_upstream.py
```

This checks that PostgreSQL MCP is reachable and returns tools. GitHub and Trends will be verified when you connect via the dashboard.

## 6. Start the Proxy

```bash
uv run mcp-guardian --scope support-agent
```

The proxy starts with:
- **MCP endpoint** at `http://localhost:9000/mcp`
- **Web dashboard** at `http://localhost:9000/`

The startup output shows a savings report:

```
mcp-guardian started
  Scope:          support-agent
  Servers:        3
  Tools in scope: 7
  Direct cost:    108,549 tokens
  Proxy cost:     155 tokens
  Savings:        99.9%
  Deferred:       github, trends (will index on first call)
  Dashboard:      http://0.0.0.0:9000/
```

Servers that require OAuth or an API key are **deferred** at startup and show as "Pending" on the dashboard.

## 7. Use the Dashboard

Open `http://localhost:9000/` in your browser. The dashboard shows:

- **Server cards** with status (Connected, Pending OAuth, Needs API Key)
- Connected servers auto-expand to show their tools
- Click **Connect** on OAuth servers to trigger browser-based authorization
- Paste API keys for `bearer_env` servers (saved in browser localStorage)
- **Tool Search** to find tools across all connected servers

## 8. Chat Demo (Optional)

The dashboard includes a **Chat Demo** tab that lets you converse with your tools using an LLM. It shows token accounting in real time — comparing what a direct connection would cost vs the proxy.

To enable it, set the LLM env vars in `.env`:

```bash
GUARDIAN_LLM_API_KEY=sk-your-key
```

Then open the dashboard, switch to the "Chat Demo" tab, and type a natural language query like "list all tables" or "latest trends in India". The agent uses the same progressive discovery pattern (search → schema → execute) and streams each step live.

Any OpenAI-compatible endpoint works — set `GUARDIAN_LLM_BASE_URL` to point at Ollama, Azure OpenAI, etc.

## 9. Connect a Client

Point any MCP client at `http://localhost:9000/mcp`. It will see three tools:

- `search_tools` — discover available tools
- `get_schema` — get parameters for a tool
- `execute_tool` — run a tool

## 10. Graceful Shutdown

Press `Ctrl+C` to stop the proxy. It cleanly closes all cached OAuth client sessions before exiting.

## 11. Run Tests

```bash
# Unit tests
uv run pytest tests/ -v

# Integration tests (requires upstream servers running)
uv run pytest tests/ -v -m integration
```

## 12. Docker Alternative

If you prefer Docker:

```bash
docker compose up --build
```

This starts both PostgreSQL MCP and the guardian proxy. Connect your client to `http://localhost:9000/mcp` and open the dashboard at `http://localhost:9000/`.
