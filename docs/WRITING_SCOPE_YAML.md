# Writing scope.yaml

This guide covers every section and auth type in `scope.yaml` -- the
single configuration file that controls which MCP servers mcp-guardian
connects to, what tools each scope exposes, and how authentication
works.

---

## File Structure

```yaml
upstream_servers:    # 1. Define your MCP servers
  server-name:
    url: ...
    auth: ...

scopes:              # 2. Define tool-access scopes
  scope-name:
    servers:
      server-name:
        allowed_tools: ...

audit:               # 3. (Optional) Audit logging settings
  enabled: true
```

---

## 1. Upstream Servers

Each entry under `upstream_servers` defines a connection to one MCP
server. The key becomes the server's name throughout the rest of the
config.

### Required fields

| Field | Description |
|-------|-------------|
| `url` | Full URL to the MCP server endpoint |
| `url_env` | **Alternative to `url`** — name of an environment variable containing the URL. Use when the URL contains credentials. |

You must provide exactly one of `url` or `url_env`.

### Optional fields

| Field | Default | Description |
|-------|---------|-------------|
| `transport` | `auto` | Transport protocol: `auto`, `streamable-http`, or `sse` |
| `auth` | `type: none` | Authentication block (see below) |

---

## 2. Auth Types

### `none` — No authentication

```yaml
postgres:
  url_env: POSTGRES_MCP_URL
  auth:
    type: none
```

Use for servers that don't require auth, or where credentials are
embedded in the URL (set via `url_env` so they stay out of YAML).

### `bearer_env` — API key / Bearer token

```yaml
trends:
  url: https://x-twitter.api.trendsmcp.ai/mcp
  auth:
    type: bearer_env
    value_env: TRENDS_API_KEY     # optional env var name
```

The proxy resolves the bearer token from four sources in priority
order:

1. **Client `Authorization` header** — if the MCP client sends an
   `Authorization: Bearer <token>` header, that token is used first.
2. **KeyStore** (dashboard UI or external store) — if a user entered a
   key via the web dashboard, it's cached in the KeyStore and used next.
3. **Environment variable** (`value_env`) — if the env var is set, its
   value is used as the bearer token.
4. **None** — if no key is available from any source, the server is
   deferred at startup. The dashboard will show an API key input field.

This means you can:

- Set `TRENDS_API_KEY` in `.env` for headless / CI deployments
- Enter the key in the dashboard UI for interactive use
- Omit `value_env` entirely and rely purely on the dashboard

The `value_env` field is optional. If omitted, the server will always
start deferred and wait for a key via the dashboard.

**Dashboard behavior:**

- Deferred `bearer_env` servers show a key input field + "Save" button
- Keys are stored in the browser's `localStorage` for persistence
  across page reloads
- On page load, saved keys are automatically sent to the backend
- Connected servers show a "Remove Key" button to clear the key

### `static_header` — Custom header from env var

```yaml
custom-api:
  url: https://api.example.com/mcp
  auth:
    type: static_header
    header: X-API-Key            # header name (default: Authorization)
    value_env: CUSTOM_API_KEY    # env var holding the value
```

Sets a specific HTTP header with a value from an environment variable.
Use when the upstream expects a non-standard auth header.

### `token_passthrough` — Forward client's Authorization header

```yaml
gateway:
  url: https://internal-gateway.example.com/mcp
  auth:
    type: token_passthrough
```

Forwards the `Authorization` header from the MCP client (e.g., Cursor,
Claude) directly to the upstream server. No env var needed — the
credential comes from whoever is calling the proxy.

Use cases:
- Internal gateways that validate the end-user's token
- Per-user auth without the proxy managing credentials
- Testing with curl: `curl -H "Authorization: Bearer xxx" ...`

### `oauth` — Browser-based OAuth flow

```yaml
github-oauth:
  url: https://gateway.truefoundry.ai/tfy-eo/mcp/github-mcp/server
  auth:
    type: oauth
```

The proxy delegates the full OAuth flow to `fastmcp`'s built-in OAuth
client. On first use, a browser window opens for authorization. The
token is cached in a persistent client connection for the session.

#### Pre-registered OAuth clients

If the MCP server supports OAuth discovery (`/.well-known/oauth-authorization-server`)
but does **not** support dynamic client registration (RFC 7591), you can
provide a pre-registered `client_id` and optional `client_secret_env`:

```yaml
github:
  url: https://api.githubcopilot.com/mcp/
  auth:
    type: oauth
    client_id: Iv23li4KZ7YdOCyEdolv
    client_secret_env: GITHUB_OAUTH_SECRET   # optional, for confidential clients
```

| Field | Required | Description |
|-------|----------|-------------|
| `client_id` | No | Pre-registered OAuth client ID. Skips dynamic registration. |
| `client_secret_env` | No | Env var holding the client secret. Only needed for confidential clients. |

When `client_id` is set, `fastmcp` still discovers auth/token URLs from
`/.well-known` but uses your credentials instead of registering a new client.

If the server has **neither** OAuth discovery nor dynamic registration
(e.g., raw GitHub, Slack, Notion), use an MCP gateway that provides
the discovery endpoint.

**Dashboard behavior:**

- OAuth servers that haven't been authorized show a "Connect" button
- Clicking "Connect" triggers the browser-based OAuth flow
- After completing OAuth, tools auto-expand on the dashboard
- Connected OAuth servers show a "Disconnect" button

---

## 3. Scopes

Scopes define **which tools are visible** from each server. You can
create any number of scopes (not limited to the example
`support-agent` / `developer`).

```yaml
scopes:
  my-scope:
    description: "What this scope is for"
    servers:
      server-name:
        allowed_tools: ...
        blocked_tools: ...
```

### Tool access rules

**Allow all tools:**

```yaml
postgres:
  allowed_tools: "*"
```

**Allow all except specific tools:**

```yaml
postgres:
  allowed_tools: "*"
  blocked_tools:
    - pg_drop_table
    - pg_truncate
```

**Allow only specific tools:**

```yaml
postgres:
  allowed_tools:
    - pg_read_query
    - pg_list_tables
    - pg_describe_table
```

When `allowed_tools` is a list, `blocked_tools` is ignored.

### One scope per proxy instance

The proxy runs with one active scope, specified at startup:

```bash
mcp-guardian --config scope.yaml --scope support-agent
```

To run multiple scopes simultaneously, start multiple proxy instances
on different ports:

```bash
mcp-guardian --scope support-agent --port 9000 &
mcp-guardian --scope developer --port 9001 &
```

---

## 4. Audit

```yaml
audit:
  enabled: true              # default: true
  log_file: audit.log        # default: audit.log
  include_params: true       # log tool call parameters (default: true)
```

Set `include_params: false` in production if parameters may contain
sensitive data (PII, credentials, etc.).

---

## 5. Adding a New MCP Server

Step-by-step:

1. **Add the server** under `upstream_servers`:

```yaml
upstream_servers:
  my-new-server:
    url: https://my-server.example.com/mcp
    auth:
      type: bearer_env
      value_env: MY_SERVER_KEY
```

2. **Add it to each scope** that should have access:

```yaml
scopes:
  developer:
    servers:
      my-new-server:
        allowed_tools: "*"
  support-agent:
    servers:
      my-new-server:
        allowed_tools:
          - read_data
          - list_items
```

3. **Set the env var** (if using `bearer_env` with `value_env`):

```bash
echo 'MY_SERVER_KEY=sk-xxx' >> .env
```

Or enter the key in the dashboard after starting the proxy.

4. **Restart the proxy** to pick up config changes.

---

## 6. Extending the KeyStore

By default, API keys entered via the dashboard are stored in memory
(lost on restart — but auto-restored from the browser's localStorage
on page load).

For production deployments, you can implement a custom `KeyStore`:

```python
from mcp_guardian.keystore import KeyStore

class RedisKeyStore(KeyStore):
    def __init__(self, redis_url: str):
        import redis.asyncio as redis
        self._redis = redis.from_url(redis_url)

    async def get(self, server_name: str) -> str | None:
        val = await self._redis.get(f"guardian:key:{server_name}")
        return val.decode() if val else None

    async def set(self, server_name: str, key: str) -> None:
        await self._redis.set(f"guardian:key:{server_name}", key)

    async def delete(self, server_name: str) -> bool:
        return bool(await self._redis.delete(f"guardian:key:{server_name}"))

    async def has(self, server_name: str) -> bool:
        return bool(await self._redis.exists(f"guardian:key:{server_name}"))
```

Pass it when constructing the `UpstreamManager`:

```python
from mcp_guardian.keystore import KeyStore
from mcp_guardian.upstream import UpstreamManager

store = RedisKeyStore("redis://localhost:6379")
upstream = UpstreamManager(servers, key_store=store)
```

---

## Full Example

```yaml
upstream_servers:
  github:
    url: https://api.githubcopilot.com/mcp/
    auth:
      type: oauth
      client_id: Iv23li...
      client_secret_env: GITHUB_OAUTH_SECRET

  postgres:
    url_env: POSTGRES_MCP_URL
    auth:
      type: none

  trends:
    url: https://x-twitter.api.trendsmcp.ai/mcp
    auth:
      type: bearer_env
      value_env: TRENDS_API_KEY

scopes:
  support-agent:
    description: "Read-only tools for support agents"
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

  developer:
    description: "Full access minus destructive operations"
    servers:
      github:
        allowed_tools: "*"
        blocked_tools:
          - delete_file
          - push_files
      postgres:
        allowed_tools: "*"
        blocked_tools:
          - pg_drop_table
          - pg_truncate
      trends:
        allowed_tools:
          - trendsMCP___get_top_trends
          - trendsMCP___get_trends
          - trendsMCP___get_growth

audit:
  enabled: true
  log_file: audit.log
  include_params: true
```
