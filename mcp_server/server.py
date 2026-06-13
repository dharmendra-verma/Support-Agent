"""ResolveDesk MCP server (FastMCP) — backend tools for the support agent.

Tool **descriptions are the model's primary selection mechanism**, so each one states:
purpose, input format, an example query, edge cases, and the boundary versus its most
similar sibling. The two easily-confused tools — `get_customer` (who the customer is) and
`lookup_order` (a specific purchase) — cross-reference each other so the model routes
"check my order #12345" to `lookup_order`, not `get_customer`.

Descriptions live in constants so the FastMCP server and the routing-test schemas share one
source of truth. See `docs/mcp-tools.md` for the before/after description study notes.
"""
from __future__ import annotations

from mcp_server.backend import REFUND_AUTO_APPROVE_LIMIT, Backend, NotFoundError
from mcp_server.errors import BusinessRuleViolation, ValidationFailure, tool_errors

_backend = Backend.seeded()

# --- descriptions (the selection-critical text) -----------------------------

GET_CUSTOMER_DESC = (
    "Fetch a CUSTOMER ACCOUNT / PROFILE by customer id or email. Returns name, email and "
    "tier — it does NOT return their orders.\n"
    "Input: a customer id like 'C-1001', OR an email like 'jane@example.com'.\n"
    "Example queries: 'look up the account for jane@example.com', 'pull up customer C-1002', "
    "'what tier is this customer on?'.\n"
    "Edge case: an unknown id/email returns a not_found error.\n"
    "Boundary: use this for WHO the customer is (profile, contact, tier). For anything about a "
    "specific order or purchase by its number, use lookup_order instead."
)

LOOKUP_ORDER_DESC = (
    "Look up a single ORDER by its order number. Returns status, items and total.\n"
    "Input: an order id like '12345' (a leading '#' is fine).\n"
    "Example queries: 'check my order #12345', 'has order 98765 shipped?', "
    "'what did I buy on order A-555?'.\n"
    "Edge case: an unknown order id returns a not_found error.\n"
    "Boundary: use this whenever the request is about a specific order, purchase, or shipment "
    "(e.g. 'my order #...'). Use get_customer only for account/profile lookups, never for orders."
)

PROCESS_REFUND_DESC = (
    "Issue a refund against an existing order — this MOVES MONEY back to the customer.\n"
    "Input: order_id (e.g. '12345'), amount (number), and a short reason.\n"
    "Example query: 'refund $40 on order 12345, the item arrived damaged'.\n"
    f"Edge cases: amount at or under {REFUND_AUTO_APPROVE_LIMIT:.0f} is auto-approved; above it the "
    "tool returns requires_approval and you should call escalate_to_human. Unknown order returns "
    "not_found.\n"
    "Boundary: use only to refund money — never for lookups."
)

ESCALATE_DESC = (
    "Hand the case off to a human agent with full context. Returns a ticket id.\n"
    "Input: reason (why a human is needed) and optional context (what you already tried/found).\n"
    "Example queries: a refund exceeds the auto-approve limit, the customer is dissatisfied, or "
    "the request is outside the available tools.\n"
    "Edge case: always include enough context for the human to act without re-asking the customer.\n"
    "Boundary: a last resort once tools cannot resolve the request — not for routine lookups."
)

# Neutral system prompt: deliberately free of keyword cues that would override the tool
# descriptions (it does NOT say e.g. "for orders, call lookup_order"). Routing must come
# from the descriptions, not the prompt. See docs/mcp-tools.md "System-prompt review".
SYSTEM_PROMPT = (
    "You are ResolveDesk, a customer-support agent. Use the provided tools to look up accounts "
    "and orders and to process refunds or escalate when needed. Pick the single most appropriate "
    "tool for each request based on the tool descriptions."
)


# --- handlers (call the backend, return structured results) -----------------


# Failures are surfaced as structured isError envelopes by @tool_errors (SA-11); a
# not_found is a VALID empty result (successful query, no match) — NOT an error.


@tool_errors
def get_customer(identifier: str) -> dict:
    if not identifier or not identifier.strip():
        raise ValidationFailure("identifier is required (a customer id or email)")
    try:
        return {"ok": True, "customer": _backend.get_customer(identifier)}
    except NotFoundError as exc:
        return {"ok": False, "error": "not_found", "detail": str(exc)}


@tool_errors
def lookup_order(order_id: str) -> dict:
    if not order_id or not str(order_id).strip():
        raise ValidationFailure("order_id is required")
    try:
        return {"ok": True, "order": _backend.get_order(order_id)}
    except NotFoundError as exc:
        return {"ok": False, "error": "not_found", "detail": str(exc)}


@tool_errors
def process_refund(order_id: str, amount: float, reason: str) -> dict:
    if amount is None or amount <= 0:
        raise ValidationFailure("amount must be a positive number")
    try:
        order = _backend.get_order(order_id)
    except NotFoundError as exc:
        return {"ok": False, "error": "not_found", "detail": str(exc)}
    if amount > REFUND_AUTO_APPROVE_LIMIT:
        return {
            "ok": False, "error": "requires_approval",
            "detail": (f"amount {amount} exceeds the auto-approve limit "
                       f"{REFUND_AUTO_APPROVE_LIMIT:.0f}; call escalate_to_human"),
        }
    if amount > order["total"]:
        raise BusinessRuleViolation(
            f"refund {amount} exceeds order total {order['total']}",
            "We can only refund up to the amount paid on this order.")
    return {"ok": True, "refund": _backend.record_refund(order_id, amount, reason)}


@tool_errors
def escalate_to_human(reason: str, context: str = "") -> dict:
    return {"ok": True, "ticket": _backend.record_escalation(reason, context)}


# Anthropic-style tool schemas — the single source the routing test sends to the model
# and the FastMCP server registers from.
TOOL_SCHEMAS = [
    {"name": "get_customer", "description": GET_CUSTOMER_DESC,
     "input_schema": {"type": "object",
                      "properties": {"identifier": {"type": "string"}},
                      "required": ["identifier"]}},
    {"name": "lookup_order", "description": LOOKUP_ORDER_DESC,
     "input_schema": {"type": "object",
                      "properties": {"order_id": {"type": "string"}},
                      "required": ["order_id"]}},
    {"name": "process_refund", "description": PROCESS_REFUND_DESC,
     "input_schema": {"type": "object",
                      "properties": {"order_id": {"type": "string"},
                                     "amount": {"type": "number"},
                                     "reason": {"type": "string"}},
                      "required": ["order_id", "amount", "reason"]}},
    {"name": "escalate_to_human", "description": ESCALATE_DESC,
     "input_schema": {"type": "object",
                      "properties": {"reason": {"type": "string"},
                                     "context": {"type": "string"}},
                      "required": ["reason"]}},
]

HANDLERS = {
    "get_customer": get_customer,
    "lookup_order": lookup_order,
    "process_refund": process_refund,
    "escalate_to_human": escalate_to_human,
}


def build_server():
    """Construct the FastMCP server (lazy import keeps this module test-friendly)."""
    from fastmcp import FastMCP

    from mcp_server.resources import register_resources

    mcp = FastMCP("resolvedesk")
    mcp.tool(get_customer, name="get_customer", description=GET_CUSTOMER_DESC)
    mcp.tool(lookup_order, name="lookup_order", description=LOOKUP_ORDER_DESC)
    mcp.tool(process_refund, name="process_refund", description=PROCESS_REFUND_DESC)
    mcp.tool(escalate_to_human, name="escalate_to_human", description=ESCALATE_DESC)
    register_resources(mcp)  # refund/returns policy catalog (SA-12)

    from agent.tooling import register_extra_tools  # lazy: avoids a circular import

    register_extra_tools(mcp)  # scoped tools, e.g. check_refund_status (SA-13)
    return mcp


if __name__ == "__main__":
    build_server().run()
