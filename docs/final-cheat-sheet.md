# MCP Dev Summit — Cheat Sheet + Code Mode Comparison (Updated)

## CODE MODE vs YOUR PROXY: THE FULL PICTURE

### What FastMCP Code Mode Actually Does

FastMCP Code Mode is a server-side transform shipped in FastMCP 3.1
(March 2026). The server author adds one line:

```python
from fastmcp import FastMCP
from fastmcp.experimental.transforms.code_mode import CodeMode

mcp = FastMCP("my-server", transforms=[CodeMode()])
```

This replaces the server's raw tools with meta-tools:
- `search(query)` — returns tool names + brief descriptions
- `get_schemas(tools)` — returns full schemas for specific tools
- `execute_code(code)` — runs Python in a sandbox (Monty sandbox)

The agent discovers tools through search, then writes a Python script
that calls multiple tools, and the script runs server-side. Only the
final result comes back to the LLM.

### How Code Mode Discovery Works (three detail levels)

```
Brief:    tool_name + one-line description       (~16 tokens/tool)
Detailed: compact markdown with param names/types (~80-200 tokens)
Full:     complete JSON Schema                    (~300-1400 tokens)
```

The LLM navigates: search → brief results → get_schemas → full for
selected tools → write code → execute.

### What Code Mode Solves

1. **Discovery cost**: ~95-99% token reduction on tool schemas
2. **Round-trip cost**: chains multiple tool calls in one script
   execution. 5 tool calls = 1 round trip instead of 5.
3. **Intermediate result cost**: results from chained calls stay in
   the sandbox. Only the final output enters the LLM's context.

### What Code Mode Requires

- Server author must opt in (add transforms=[CodeMode()])
- Client must support the code execution pattern
- Sandbox runtime (Monty sandbox, Docker, or custom SandboxProvider)
- Currently experimental in FastMCP (interface stable, details may change)

### Where Code Mode Falls Short

- **Third-party servers**: The GitHub community MCP server, Slack server,
  Sentry server, most vendor servers — they don't have Code Mode. You
  can't add it without forking the server.
- **Simple clients**: Claude Desktop, basic agent frameworks — they use
  standard tools/call, not code execution.
- **No tool scoping**: Code Mode shows all tools. No per-agent, per-role,
  per-scope filtering.
- **No auth management**: Each server handles its own auth. No centralized
  credential management across servers.

### Where Your Proxy is Different

| Capability | Code Mode | mcp-guardian |
|---|---|---|
| Works with unmodified 3rd-party servers | No | Yes |
| Works with every MCP client | No (needs code exec) | Yes |
| Reduces discovery tokens | Yes (~95-99%) | Yes (~96%) |
| Reduces execution round trips | Yes (chains in sandbox) | No |
| Tool scoping / RBAC | No | Yes |
| Auth injection | No | Yes |
| Audit logging | No | Yes |
| Sandbox required | Yes | No |
| Handles multi-server | Per-server | One proxy, all servers |

### The Complementary Argument (use this exact framing)

"If you control the server → add Code Mode. Maximum efficiency.

If you don't control the server → put the proxy in front. Progressive
disclosure without modifying anything upstream.

For your full MCP fleet → use both. Internal servers get Code Mode.
Third-party servers go through the proxy. The proxy can even sit in
front of a Code Mode server for scoping and auth. They don't conflict."

```
Your MCP Fleet
├── Internal servers (you author these)
│   └── Add Code Mode directly
│       ├── Progressive disclosure ✓
│       ├── Code execution ✓
│       └── Round-trip reduction ✓
│
├── Third-party servers (GitHub, Slack, vendor servers)
│   └── Put mcp-guardian in front
│       ├── Progressive disclosure ✓
│       ├── Tool scoping ✓
│       ├── Auth injection ✓
│       └── Audit logging ✓
│
└── Future: proxy with code execution meta-tool
    └── Code Mode for servers that don't have it natively
```

### Future Work: Code Execution in the Proxy

The natural evolution: add an `execute_code` meta-tool to mcp-guardian
that runs scripts in a sandbox, calling upstream tools. This would give
you Code Mode for any server — same round-trip reduction, same
intermediate result handling, but at the proxy layer.

Mention this in the talk as "what's next." Don't oversell it. Say:
"The architecture supports it. I haven't built it yet."

---

## REAL-WORLD LEARNINGS FROM BUILDING A PUBLIC MCP PLAYGROUND

_These are things you learned firsthand building the MCP Playground.
Use them for credibility. Not all belong in the talk — pick the ones
that fit naturally._

### Transport Is Not Uniform

Different MCP servers use different transports. You discovered this
when DeepWiki (SSE) failed with the same client code that worked for
Calculator (Streamable HTTP):

```
Calculator MCP → Streamable HTTP → worked immediately
DeepWiki MCP   → SSE transport   → "McpError: Session terminated"
```

Fix: the proxy (and any MCP client) needs transport auto-detection
with fallback. This is NOT theoretical — it's a real production issue.
Mention in Limitations section.

### Auth Complexity Is the Real Iceberg

Your talk covers auth injection (static headers). But from building
the playground, you know the full picture:

| Auth Type | Complexity | What You Learned |
|---|---|---|
| No Auth | Trivial | Some servers serve at `/`, some at `/mcp`. URL discovery is the real issue. |
| API Key (Shared) | Easy | One key, inject as header. Works. |
| OAuth2 (Per-User) | Hard | Need IdP (Auth0), External Identity in gateway, per-user token storage, consent flow, refresh. Way beyond proxy scope. |

Key gotcha: `auth_data: type: none` fails TrueFoundry's schema
validation. You must OMIT `auth_data` entirely for No Auth servers.
Also, Virtual Account subject types (`virtual-account:`, `virtualaccount:`)
don't work in MCP collaborators — VA permissions must be managed
separately.

**Use in talk:** In the Auth section, say: "Auth injection in the proxy
handles the simple cases. The per-user OAuth case — Alice connects
her GitHub, Bob connects his — that's an infrastructure layer. I
built that for my playground and it took Auth0, JWTs, External
Identity Providers, and a gateway managing per-user tokens. Don't
underestimate the auth problem."

### Tool Scoping Is a UX Problem Too

In your playground, the landing page is public (no login). Users
browse the catalog. Login is triggered only when they try to interact.
OAuth MCPs show a "Connect" button. This is progressive disclosure
at the UX level — same concept as the proxy, applied to humans.

**Use in talk (optional):** "Progressive disclosure isn't just for
agents. In my MCP playground, humans see the catalog first, tools
second, and auth third. Same principle — don't show everything
upfront."

### Rate Limiting Matters for Public MCPs

You implemented in-memory rate limiting: 10 requests per hour per
user per MCP. Without it, a public MCP playground gets abused fast.

The proxy could include rate limiting as a feature — scope.yaml could
specify per-scope rate limits. Not in v1, but architecturally it fits.

### Real Numbers From Your Deployment

| Metric | Value | Source |
|--------|-------|--------|
| Total MCP servers registered | Multiple (across all auth types) | Your playground |
| GitHub MCP tool count | 41 | Real GitHub MCP server |
| Auth types managed | 3 (No Auth, API Key, OAuth2) | Your registry |
| Transport types hit | 2 (Streamable HTTP, SSE) | Calculator vs DeepWiki |
| Auth0 → TrueFoundry setup steps | 8 (app, API, authorize, IdP, Identity, collaborators, frontend, test) | Your docs |
| Time to add a new MCP via YAML | ~5 min (config.yaml + display.yaml + tfy apply) | Your workflow |

---

## WHAT THE OFFICIAL MCP SPEC NOW SAYS

**Critical context for the talk.** The MCP spec's Client Best Practices
page (modelcontextprotocol.io/docs/develop/clients/client-best-practices)
now officially recommends progressive discovery:

> "Loading every tool definition into the model's context window upfront
> wastes tokens, increases latency, and degrades model performance."

The spec recommends:
- Progressive discovery: search → get schema → execute (your 3 meta-tools)
- Programmatic tool calling: write code that chains calls (Code Mode)
- Threshold switching: load all tools if small set, switch at 1-5% of context
- Search strategies: keyword (BM25, regex) or embedding-based

**What the spec provides:** A recommendation to clients.
**What the spec does NOT provide:** A ready-to-use implementation, tool scoping, auth management, audit logging.
**What mcp-guardian provides:** The spec's recommended patterns as a proxy — so any client gets them without client-side changes.

**Your framing:** "The spec validates the problem and recommends the pattern. I built the infrastructure implementation."

---

## ECOSYSTEM CONTEXT: WHAT EXISTS TODAY

### Solutions for Discovery Cost (Pattern 1: Progressive Disclosure)

| Solution | Approach | Status |
|---|---|---|
| **MCP Spec (Client Best Practices)** | **Official recommendation: search → schema → execute** | **Spec (recommendation only, no implementation)** |
| FastMCP Code Mode | Server-side transform, code execution | Production (experimental flag) |
| Cloudflare Code Mode | Server-specific, covers 2500 endpoints in ~1000 tokens | Production |
| Anthropic Tool Search | Client-side lazy loading in Claude Code | Production (98.7% reduction) |
| Speakeasy Dynamic Toolsets | SDK-level dynamic loading | Production (96% reduction) |
| mcp2cli | Converts MCP tools to CLI commands | Open source |
| ProDisco | TypeScript progressive disclosure framework | Open source |
| MCP Gateway (Virtual MCP Server) | Infrastructure-level tool curation + scoping | Production (TrueFoundry, others) |
| **mcp-guardian (yours)** | **Proxy-side implementation of spec patterns, works with any server + client** | **Building** |

### Solutions for Schema Cost (Pattern 2: Compression)

| Solution | Approach | Status |
|---|---|---|
| Manual schema discipline | Shorter descriptions, fewer examples | Manual effort |
| SEP-1576 | Spec proposal for mitigating token bloat | Proposal stage |
| Bifrost | Schema optimization middleware | Early stage |

### Solutions for Session Cost (Pattern 3: Session Management)

| Solution | Approach | Status |
|---|---|---|
| Nothing shipped | — | **Genuinely unsolved** |

This is why you mention session compaction as future work. It's real,
it's important, and nobody has tooling for it yet.

### Solutions for Auth (Pattern 4: Credential Management)

| Solution | Approach | Status |
|---|---|---|
| Per-server manual config | Each client manages its own tokens | Default (painful) |
| MCP Gateways | Centralized token management, per-user OAuth | Production (various) |
| mcp-guardian | Static header injection per-server | v1 (simple) |

_You've lived the full auth spectrum. Use that experience._

---

## KEY NUMBERS (memorize these)

**The MCP Tax:**
- 300–1,400 tokens per tool definition
- 41 tools from GitHub MCP alone (your own measurement)
- 55,000 tokens for 3 servers / ~40 tools (Apideck measurement)
- 143,000 of 200,000 tokens = 72% consumed (Apideck worst case)
- 244,000 tokens for Cloudflare's API surface via naive MCP

**Your real deployment:**
- Multiple MCP servers registered in your public playground
- 3 auth types managed (No Auth, API Key, OAuth2)
- 2 transport types encountered (Streamable HTTP, SSE)
- 8 steps to set up Auth0 → TrueFoundry External Identity pipeline

**The fixes:**
- FastMCP Code Mode: ~95-99% reduction (server-side)
- Cloudflare Code Mode: 2,500 endpoints in ~1,000 tokens (99.9%)
- Anthropic Tool Search: 98.7% reduction (client-side)
- Speakeasy Dynamic Toolsets: 96% reduction
- Your proxy: ~96% reduction on startup (your own measurement)

**Quality thresholds:**
- 40 tools: Cursor's enforced maximum
- 50+ tools: Claude output quality visibly degrades
- The relationship between description length and reliability is
  not monotonic — more description helps up to a point, then hurts

**Cost at scale:**
- 500 sessions/day × 40K tokens saved × $15/M tokens = ~$300/day saved
- $9,000/month in pure schema overhead eliminated

**Perplexity timeline:**
- Nov 2024: MCP launched by Anthropic
- Dec 2025: MCP donated to Linux Foundation
- Feb 2026: Perplexity launches Agent API (the alternative)
- Mar 11, 2026: Perplexity CTO publicly announces move away from MCP
- Mar 2026: FastMCP 3.1 ships Code Mode
- Jun 2026: MCP Dev Summit (your talk)

---

## THINGS NOT TO SAY

- "I invented progressive discovery" — the spec now officially
  recommends it. Say "I implemented it at the proxy layer."
- "Code Mode is wrong/bad/insufficient" — it's excellent for what
  it does. Your proxy handles a different case.
- "MCP is broken" — the protocol is fine. The spec even has the
  right recommendations now. The gap is implementation.
- "I've deployed this at X enterprise" — you haven't deployed the
  proxy at an enterprise. Say "I built this proxy" and "I've
  deployed a public MCP playground." Different claims.
- "This replaces Code Mode" — it complements Code Mode.
- "Session compaction is coming soon" — say "I'm working on it"
  or "it's future work." Don't promise timelines.
- Anything about TrueFoundry by name — this is an open-source talk.
  Say "MCP gateway" generically or "my MCP playground."

## THINGS TO SAY CONFIDENTLY

- "The MCP spec now recommends progressive discovery. But it's a
  client-side recommendation. My proxy makes it infrastructure."
- "I've built a public MCP playground with servers across every auth
  type. The context cost at scale is real. I'm not theorizing."
- "The proxy works with any MCP server AND any MCP client,
  unmodified. That's what the spec can't give you."
- "Code Mode for servers you control. Proxy for servers you don't.
  Use both."
- "Here are my benchmarks. The code and scripts are in the repo.
  Run them yourself."
- "The spec validates the problem. I built the solution."
- "Auth is the real iceberg. The proxy handles static headers.
  Per-user OAuth is an infrastructure problem. Don't underestimate it."

---

## DAY-OF CHECKLIST

### Night before
- [ ] Run all demos once. Verify everything works.
- [ ] Backup screencast recorded and saved locally
- [ ] Slides saved locally (not cloud-dependent)
- [ ] Laptop charged
- [ ] MCP Playground URL accessible (for hallway conversations)

### 1 hour before
- [ ] Start mock server, proxy, audit tail
- [ ] Open Inspector with both connections saved
- [ ] Do NOT disturb mode on everything
- [ ] Water at podium
- [ ] Deep breath

### After the talk
- [ ] Tweet slides + GitHub link + MCP Playground link + talk summary
- [ ] Be in hallway for 15 min for questions
- [ ] Show the live MCP playground on your phone/laptop to anyone interested
- [ ] Collect contacts
- [ ] Write a "what I learned giving my first talk" post (great content)
