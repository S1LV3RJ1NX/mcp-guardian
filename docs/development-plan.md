# mcp-guardian: Development Plan — Addendum

## Updates Based on Real-World MCP Deployment

These are additions/changes to the original development plan, based on
building and deploying a public MCP playground.

---

## NEW: Phase 4.5 — Transport Auto-Detection

**Add to: `src/mcp_guardian/transport.py`**

From real-world testing: Calculator MCP uses Streamable HTTP, DeepWiki
uses SSE. The proxy MUST handle both. Without this, half your upstream
servers will fail with `McpError: Session terminated`.

```python
# src/mcp_guardian/transport.py
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport, SSETransport
import httpx

async def connect_upstream(url: str, headers: dict) -> Client:
    """Connect to upstream MCP server with transport auto-detection.
    
    Tries Streamable HTTP first (preferred), falls back to SSE.
    This is critical — real MCP servers use different transports
    and there's no way to know without trying.
    """
    # Try Streamable HTTP first
    try:
        transport = StreamableHttpTransport(
            url=url,
            headers=headers,
        )
        client = Client(transport)
        async with client:
            await client.list_tools()  # probe
        return Client(StreamableHttpTransport(url=url, headers=headers))
    except Exception:
        pass
    
    # Fall back to SSE
    try:
        transport = SSETransport(
            url=url,
            headers=headers,
        )
        client = Client(transport)
        async with client:
            await client.list_tools()  # probe
        return Client(SSETransport(url=url, headers=headers))
    except Exception as e:
        raise ConnectionError(
            f"Failed to connect to {url} via both Streamable HTTP and SSE. "
            f"Visit the URL in a browser — if you see 'Not Acceptable: Client "
            f"must accept text/event-stream', the server is alive but may need "
            f"a different path (try with/without /mcp)."
        ) from e
```

**Add transport field to config (optional override):**

```yaml
# scope.yaml — updated server config
upstream_servers:
  github:
    url: http://localhost:8001/mcp
    transport: auto          # auto (default) | streamable-http | sse
    auth:
      type: bearer_env
      value_env: GITHUB_TOKEN
  deepwiki:
    url: https://mcp.deepwiki.com/mcp
    transport: sse           # force SSE (known to be SSE)
    auth:
      type: none
```

**Why this matters for the talk:** Mention transport auto-detection in
the Limitations section. Say: "I hit this exact issue — Calculator
uses Streamable HTTP, DeepWiki uses SSE. Same protocol, different
transports. The current proxy probes both. A production version
would cache the detected transport per server."

---

## UPDATED: Phase 2 — Config Loader

### Updated `scope.yaml` format

Based on real-world config patterns (each MCP as a folder with
config.yaml + display.yaml):

```yaml
# scope.yaml — production-grade config
version: "1"

upstream_servers:
  github:
    url: https://api.githubcopilot.com/mcp/
    transport: auto
    auth:
      type: bearer_env
      value_env: GITHUB_TOKEN
  
  calculator:
    url: https://calculator-mcp-server.apps.live-demo.truefoundry.cloud
    transport: auto
    auth:
      type: none
  
  deepwiki:
    url: https://mcp.deepwiki.com/mcp
    transport: sse    # known SSE server
    auth:
      type: none

scopes:
  support-agent:
    description: "Read-only support tools"
    servers:
      github:
        allowed_tools:
          - list_issues
          - get_issue
          - list_pull_requests
          - get_pull_request
      calculator:
        allowed_tools: "*"    # all tools allowed
  
  developer:
    description: "Full dev access (no destructive ops)"
    servers:
      github:
        allowed_tools:
          - list_issues
          - get_issue
          - list_pull_requests
          - get_pull_request
          - create_issue
          - create_pull_request
          - merge_pull_request
        blocked_tools:         # explicit deny list (safety net)
          - delete_repo
          - force_push
          - transfer_repo
      calculator:
        allowed_tools: "*"
      deepwiki:
        allowed_tools: "*"

audit:
  enabled: true
  log_file: audit.log
  include_params: true

rate_limit:
  enabled: true
  requests_per_hour: 10       # per-scope, per-tool
```

### New: `blocked_tools` field

From real-world experience: sometimes you want to allow most tools but
explicitly block dangerous ones. `allowed_tools` works for small sets.
`blocked_tools` is a safety net for large tool sets.

Logic: if `allowed_tools` is `"*"` and `blocked_tools` is set, allow
everything EXCEPT the blocked list.

---

## UPDATED: Phase 4 — Core Proxy Server

### Key technical decisions (updated with real learnings)

1. **Client lifecycle management.** FastMCP Client uses `async with`.
   For the proxy, reconnect per-call is safer than persistent connections.
   MCP servers can drop connections (especially SSE ones). Per-call
   with a short timeout is more reliable than keeping connections alive.

2. **Error handling.** From production experience:
   - `404 Not Found` → wrong URL (try with/without `/mcp`)
   - `Session terminated` → transport mismatch (try SSE fallback)
   - `Not Acceptable: Client must accept text/event-stream` → server is 
     alive, you're hitting it from a browser/wrong transport
   - `401 Unauthorized` → auth header not set or expired
   
   All of these should return clean JSON error messages, not stack traces.

3. **URL discovery is harder than expected.** Some servers serve at `/`,
   some at `/mcp`, some at `/sse`. The proxy should try the configured
   URL first, then common alternatives. Add a `health_check` on startup
   that validates each upstream URL.

---

## UPDATED: Phase 5 — Auth Injection

### Real-world auth complexity

The original plan has 3 auth types (none, static_header, bearer_env).
From building a public MCP playground, here's the full picture:

| Auth Type | Proxy Can Handle | Notes |
|---|---|---|
| No Auth | ✅ Yes | Some servers don't even need headers |
| API Key (static header) | ✅ Yes | Header name varies (Authorization, X-Api-Key, etc.) |
| Bearer Token (from env) | ✅ Yes | Standard pattern |
| OAuth2 (per-user) | ❌ No | Needs IdP, token storage, refresh, consent flow. Infrastructure problem, not proxy problem. |
| Token Passthrough | ⚠️ Partial | Forward the client's token to upstream. Works if client and server share an auth domain. |

**For the proxy v1:** Keep it simple (none, static_header, bearer_env).
Mention in README and talk that per-user OAuth is beyond scope — that's
what MCP gateways are for.

**Updated auth.py with better error handling:**

```python
import os
from mcp_guardian.config import ServerAuth

def get_auth_headers(auth: ServerAuth) -> dict[str, str]:
    """Build auth headers for an upstream server."""
    if auth.type == "none":
        return {}
    
    elif auth.type == "static_header":
        value = os.environ.get(auth.value_env, "")
        if not value:
            raise ValueError(
                f"Auth env var '{auth.value_env}' not set. "
                f"Set it: export {auth.value_env}=your-token"
            )
        return {auth.header: value}
    
    elif auth.type == "bearer_env":
        token = os.environ.get(auth.value_env, "")
        if not token:
            raise ValueError(
                f"Auth env var '{auth.value_env}' not set. "
                f"Set it: export {auth.value_env}=your-token"
            )
        return {"Authorization": f"Bearer {token}"}
    
    else:
        raise ValueError(
            f"Unknown auth type: '{auth.type}'. "
            f"Supported: none, static_header, bearer_env"
        )
```

---

## NEW: Phase 8.5 — Rate Limiting (Optional)

From deploying a public playground: without rate limiting, public MCPs
get abused. Add optional per-scope rate limiting.

```python
# src/mcp_guardian/rate_limit.py
import time
from collections import defaultdict

class RateLimiter:
    def __init__(self, max_requests_per_hour: int = 10):
        self.max_requests = max_requests_per_hour
        self.window_seconds = 3600
        # key: "scope:tool_name" → list of timestamps
        self._requests: dict[str, list[float]] = defaultdict(list)
    
    def check(self, scope: str, tool: str) -> tuple[bool, int, float]:
        """Returns (allowed, remaining, reset_at_timestamp)"""
        key = f"{scope}:{tool}"
        now = time.time()
        cutoff = now - self.window_seconds
        
        # Clean old entries
        self._requests[key] = [
            t for t in self._requests[key] if t > cutoff
        ]
        
        remaining = self.max_requests - len(self._requests[key])
        reset_at = self._requests[key][0] + self.window_seconds if self._requests[key] else now + self.window_seconds
        
        if remaining <= 0:
            return False, 0, reset_at
        
        self._requests[key].append(now)
        return True, remaining - 1, reset_at
```

In proxy.py, wrap execute_tool:
```python
allowed, remaining, reset_at = self.rate_limiter.check(
    self.config.active_scope, tool_name
)
if not allowed:
    return {
        "error": "Rate limit exceeded",
        "limit": self.rate_limiter.max_requests,
        "remaining": 0,
        "reset_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(reset_at)),
    }
```

---

## UPDATED: Experiment 5 — Add Real Server Benchmark

### New: Benchmark with Real GitHub MCP (41 tools)

In addition to the mock 14-tool server, benchmark against the REAL
GitHub MCP registered in your playground.

```python
# benchmarks/bench_real_github.py
"""
Benchmark against the real GitHub MCP server (41 tools).
Requires: GITHUB_TOKEN env var set.
"""
import asyncio
import tiktoken
import json
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

GITHUB_MCP_URL = "https://api.githubcopilot.com/mcp/"
enc = tiktoken.get_encoding("cl100k_base")

async def count_direct_tokens():
    transport = StreamableHttpTransport(
        url=GITHUB_MCP_URL,
        headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"}
    )
    async with Client(transport) as client:
        tools = await client.list_tools()
        total_tokens = 0
        for tool in tools:
            schema_json = json.dumps(tool.model_dump())
            tokens = len(enc.encode(schema_json))
            total_tokens += tokens
            print(f"  {tool.name}: {tokens} tokens")
        
        print(f"\nTotal: {len(tools)} tools, {total_tokens} tokens")
        return len(tools), total_tokens

asyncio.run(count_direct_tokens())
```

This gives you a REAL number for your slides: "GitHub MCP: 41 tools,
X,XXX tokens." Not a mock. Not a blog-post number. YOUR measurement.

---

## UPDATED: Risk Mitigation

| Risk | Mitigation | Status |
|------|-----------|--------|
| FastMCP Client doesn't support persistent connections | Reconnect per-call. Real-world testing confirms this works. | Known pattern |
| Token counting doesn't match actual LLM tokenization | Use cl100k_base. Note in benchmarks counts are approximate. | Acceptable |
| Search quality too low with keyword matching | Add rapidfuzz. Test both. | Optional |
| Transport mismatch breaks connections | Add transport auto-detection (Phase 4.5). You hit this in production. | **Must fix** |
| URL path varies between servers | Add URL probing on startup (try /mcp, /, /sse). | **Must fix** |
| Auth headers vary between servers | Support configurable header names. Already in v1. | Done |
| Upstream server down during demo | Pre-start all servers. Have recorded backup. | Standard prep |
| CFP rejected | You still have: open source project, blog post, benchmarks, credibility from public MCP playground. | Acceptable |

---

## UPDATED: Open Source README

Add these sections based on real experience:

### Known Gotchas

```markdown
## Known Gotchas

| Issue | Cause | Fix |
|-------|-------|-----|
| `Session terminated` on connect | Transport mismatch (server uses SSE, client uses Streamable HTTP) | Set `transport: sse` in scope.yaml for that server, or use `transport: auto` |
| `404 Not Found` on connect | Wrong URL path | Try the URL with and without `/mcp`. Visit it in a browser to check. |
| `Not Acceptable: Client must accept text/event-stream` | Server is alive, you're hitting it from browser | The URL is correct. The server only speaks MCP protocol, not HTTP. |
| Search returns no results | Keywords don't match tool names/descriptions | Try different keywords. Tool names like `list_issues` match on both "list" and "issues". |
```

### Comparison with MCP Gateways

```markdown
## mcp-guardian vs MCP Gateways

MCP Gateways (TrueFoundry, Cloudflare, etc.) provide:
- Per-user OAuth token management
- Central registry with UI
- Rate limiting, guardrails, observability
- Production deployment with HA

mcp-guardian provides:
- Tool scoping via YAML config
- Progressive disclosure (3 meta-tools)
- Auth injection (static headers)
- Audit logging
- Zero infrastructure dependencies

**Use a gateway** when you need per-user auth, a team admin UI,
and production-grade infrastructure.

**Use the proxy** when you want lightweight scoping and compression
for local development, single-user agents, or environments where
you can't add infrastructure.

They complement each other. The proxy can sit in front of a gateway
for additional scoping.
```
