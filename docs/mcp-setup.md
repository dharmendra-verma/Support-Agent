# MCP server setup & scoping (SA-12)

The ResolveDesk MCP server exposes the four tools (SA-10) **and** a refund/returns policy
catalog as resources, so the agent can read policy without burning exploratory tool calls.

## Policy catalog (resources)
`mcp_server/resources.py` publishes read-only resources at **stable URIs** (the catalog
contract — don't change without versioning):

| URI | Content |
|---|---|
| `resolvedesk://policy/refund` | auto-approve limit, escalation rule, no-refund-over-total, verify-first |
| `resolvedesk://policy/returns` | 30-day window, original-payment refund, final-sale exclusion |

Resources are read by the client directly (`resources/read`) — **not** via a tool call — so
they stay out of the tool token budget. Content is rendered from the same constants the
tools enforce (`REFUND_AUTO_APPROVE_LIMIT`), so policy and behavior never drift.

## Project scope — `.mcp.json` (committed, shared with the team)
At the repo root, `.mcp.json` defines the shared server. Credentials use **`${VAR}`
expansion** so **no secret is committed** — the value is resolved from your shell at session
start:
```json
{ "mcpServers": { "resolvedesk": { "type": "stdio", "command": "python",
  "args": ["-m", "mcp_server.server"],
  "env": { "RESOLVEDESK_API_TOKEN": "${RESOLVEDESK_API_TOKEN}" } } } }
```
Set the token in your environment before launching Claude Code:
```bash
export RESOLVEDESK_API_TOKEN=...   # PowerShell: $env:RESOLVEDESK_API_TOKEN="..."
```
`${VAR:-default}` is also supported. **Hand-edit `.mcp.json`** to keep the `${...}` literal —
`claude mcp add` can resolve placeholders into the file. First load prompts for approval
(`/mcp`), since a project server launches a process.

## User scope — `~/.claude.json` (personal, NOT shared via git)
Add a personal/experimental server to your global config (machine-scoped, every project):
```bash
claude mcp add --scope user resolvedesk-dev -- python -m mcp_server.server
# stored under the top-level "mcpServers" key in ~/.claude.json (%USERPROFILE%\.claude.json on Windows)
```
**Both scopes load at once:** tools from the project `resolvedesk` server and the user
`resolvedesk-dev` server are available in the same session (on name collision: local > project > user).

## Tool descriptions beat built-ins (AC)
The SA-10 descriptions are specific enough that the agent prefers `lookup_order` for an order
question over a generic/built-in alternative (e.g. web search) — see `docs/mcp-tools.md`.

## Verifying both scopes (test evidence)
1. `claude mcp list` → shows `resolvedesk` (project) and `resolvedesk-dev` (user).
2. In a session, `/mcp` → approve the project server; both servers' tools appear.
3. Read a resource (`resolvedesk://policy/refund`) and confirm the content loads without a
   tool call. Record the output here as evidence.
