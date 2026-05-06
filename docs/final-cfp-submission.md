# MCP Dev Summit Bengaluru — Final CFP Submission (Updated)

**CFP Deadline:** Monday, 20 April 2026 at 11:59 PM IST
**Event:** 9–10 June 2026, Bengaluru

---

## SESSIONIZE SUBMISSION

### Title

**"Putting MCP on a Diet: A Proxy for Tool Scoping and Context Compression"**

### Track

**Building with MCP**
_Practical implementations, design patterns, tools, integrations, and
real-world experiences building MCP servers, clients, and applications._

### Submission Type

Session Presentation (25 minutes)

### Abstract

Connect three MCP servers — GitHub, Slack, Sentry — and 40 tool
schemas consume 55,000 tokens before the agent reads a single word
of the user's query. Connect ten servers and you've lost a third of
your context window to tool descriptions the agent may never use.

The MCP spec now officially acknowledges this problem. The Client
Best Practices page recommends progressive discovery — search for
tools, load schemas on demand. But it's a recommendation to clients:
every client has to implement it independently. And the spec doesn't
address tool scoping or centralized auth.

I know this firsthand. I've built and deployed a public MCP
playground — GitHub (41 tools alone), Slack, code interpreters —
with per-user OAuth, tool scoping, and rate limiting. The context
cost at that scale is real.

Solutions exist at the server level: FastMCP Code Mode transforms
servers to use progressive disclosure with code execution in a
sandbox. But it requires the server author to opt in. Most MCP
servers in the wild will never add Code Mode.

I built mcp-guardian, an open-source Python proxy that implements
the spec's recommended patterns at the infrastructure layer — so
every client benefits without changing a line of code. It does
three things:

First, tool scoping. The proxy filters the tools/list response
against a YAML config, so agents only see tools they're allowed to
use. delete_repo doesn't exist in the agent's world — not blocked,
not restricted, removed from the schema entirely.

Second, progressive disclosure at the proxy layer. Instead of
forwarding full JSON Schemas (300–1,400 tokens per tool), the proxy
exposes three meta-tools: search_tools (grep/fuzzy match over a
local tool index), get_schema (full schema on demand for a specific
tool), and execute_tool (forwards the call to the upstream server).
The agent starts with ~300 tokens instead of ~8,000 and loads full
schemas only for the tools it actually needs.

Third, auth injection and audit logging. The proxy manages
credentials per upstream server and logs every tool call — who
called what, when, with what params. Features the spec recommends
but doesn't implement.

In this talk, I'll live-demo the proxy against a mock 14-tool GitHub
server: direct connection at ~8,000 tokens, then through the proxy
at ~300 tokens with the same tools available on demand. I'll walk
through the JSON-RPC interception that makes this work, share token
count benchmarks comparing direct vs. proxy vs. FastMCP Code Mode,
and explain where these approaches are complementary — the proxy
handles discovery cost for servers you don't control, while Code
Mode reduces execution round trips for servers you do.

The project is open source, ~600 lines of Python, and you can run it
locally in five minutes.

### Speaker Bio

Prathamesh Saraf is a Senior Forward Deployed Engineer who works with
enterprises and startups to build and deploy LLM and AI agent systems.
He has built and deployed a public-facing MCP playground, handling OAuth2 authentication, tool scoping,
and per-user rate limiting at scale. He is the author of "My Adventures
with Large Language Models," a technical book on building LLM
architectures from scratch in PyTorch (Transformers through DeepSeek).
He builds mcp-guardian as an open-source proxy for MCP tool scoping
and context compression. Based in Bangalore, India.

### Tags/Topics

MCP, context engineering, progressive disclosure, tool scoping,
proxy, token optimization, open source, Python, FastMCP

---

## WHY THIS TALK FITS THE EVENT

1. **Timely.** The MCP spec now officially recommends progressive
   discovery. You're showing a working implementation that goes
   beyond the spec's client-side recommendation.

2. **Novel angle.** The spec recommends progressive discovery as a
   client pattern. FastMCP Code Mode is server-side. Your proxy is
   infrastructure-level — works with unmodified servers AND
   unmodified clients. That's genuinely new.

3. **Real-world deployment.** You've built a public MCP playground with servers across every auth type. You're not theorizing — you've hit the auth
   issues, transport quirks, and token costs firsthand.

4. **Live demo with real numbers.** Not blog-post benchmarks. Your
   own measurements from your own proxy and your own deployment.

5. **Builder talk, not analysis talk.** "I built this, here's how
   it works, here are the numbers" is the right format for
   "Building with MCP" track.

6. **Gives the audience something to take home.** GitHub repo,
   5-minute setup, MIT license. Plus a live playground they can visit.

7. **Honest about scope.** You compare with Code Mode and explain
   where each approach wins. You're not overselling a proxy as
   the solution to everything.
