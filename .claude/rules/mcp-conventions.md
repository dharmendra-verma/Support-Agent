---
description: MCP tool-server conventions; loads when editing the MCP server or tool registry.
paths:
  - "mcp_server/**/*"
  - "src/agent/tools.py"
---

# MCP / tool conventions (path-scoped → tool code)

- Tools use the **registry pattern**: one `Tool` bundles name + JSON `input_schema` +
  handler. Register once; project into both the reference loop (`ToolRegistry`) and the
  SDK `@tool` / `create_sdk_mcp_server` server. Never define a tool's schema twice.
- **Structured errors.** A tool returns a decision-enabling error payload (what failed,
  why, what the caller can do) — not a bare stack trace. Set `is_error` on the
  `tool_result` for genuine runtime failures.
- An unregistered tool name is a **config bug**: fail fast, don't feed a fabricated
  error back to the model.
- Validate inputs against the declared schema; keep handlers pure and side-effect-scoped.
- (FastMCP, arriving in SA-10) expose backend ops — customers, orders, refunds,
  escalation — with explicit, typed signatures and resource definitions.
