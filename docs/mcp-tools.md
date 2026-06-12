# MCP tools — descriptions as the selection mechanism (SA-10)

The agent reaches the backend through four FastMCP tools (`mcp_server/server.py`):
`get_customer`, `lookup_order`, `process_refund`, `escalate_to_human`, backed by seeded
fixtures in `mcp_server/backend.py`. **Tool descriptions are how the model picks a tool**, so
they're written deliberately — and iterated until routing is reliable.

## The misrouting problem
`get_customer` and `lookup_order` are easy to confuse: a request like *"check my order
#12345"* says "my", which tempts the model toward the *customer* tool. With thin
descriptions the model misroutes. The fix is descriptions that draw an explicit boundary and
**cross-reference each other**.

### Before → after (study notes)
| Tool | ❌ Before (thin) | ✅ After (differentiated) |
|---|---|---|
| `get_customer` | "Get a customer." | "Fetch a customer ACCOUNT/PROFILE by id or email … returns name/email/tier, **not orders** … **Boundary:** use for *who the customer is*; for a specific order use **lookup_order**." |
| `lookup_order` | "Look up an order." | "Look up a single ORDER by its number … status/items/total … **Boundary:** use for any *specific order/purchase/shipment* ('my order #…'); use **get_customer** only for account lookups, never orders." |

Every description covers five facets: **purpose · input format · example queries · edge
cases · boundary vs the similar tool** (asserted in `tests/test_tool_routing.py`).

## System-prompt review
Routing must come from the **descriptions**, not from keyword cues hard-coded in the system
prompt. `server.SYSTEM_PROMPT` is intentionally neutral — it does **not** say things like
"for orders, call `lookup_order`" (a test asserts no tool name appears in it). Putting
routing logic in the prompt would mask weak descriptions and break the moment a tool is
reused elsewhere.

## Routing test (≥9/10)
`tests/test_tool_routing.py::test_get_customer_vs_lookup_order_routing` sends 10 ambiguous
prompts (5 order-ish, 5 account-ish) to the real model with the four tool schemas and asserts
the right tool is selected **≥9/10**. It is **skipped without `ANTHROPIC_API_KEY`** (the
rest of the suite is fully offline):
```bash
ANTHROPIC_API_KEY=sk-ant-... pytest tests/test_tool_routing.py -k routing
# optional: ROUTING_MODEL=claude-sonnet-4-6 (default)
```
If a prompt misroutes, the assertion prints which one — tighten that tool's **Boundary** line
and re-run. Keep descriptions *precise, not verbose*: every token is sent on every turn.

## Edge cases the tools surface (structured, not stack traces)
- unknown customer/order → `{"ok": false, "error": "not_found", …}`
- refund over the auto-approve limit (`REFUND_AUTO_APPROVE_LIMIT`) → `requires_approval`,
  steering the model to `escalate_to_human` (real enforcement is a hook in SA-14)
