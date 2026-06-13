"""Tool distribution + tool_choice strategies (SA-13).

Selection reliability degrades as tools grow (~4–5 per agent is the sweet spot; ~18 fails),
so each agent/subagent gets only its **role-relevant** tools. Some workflow steps must
guarantee a tool call (`tool_choice="any"`) or force a specific tool first
(`{"type":"tool","name":...}`). Forced selection only governs the NEXT response, so a
constrained flow chains one turn per step.

Exam: D2 TS 2.3. See `docs/tool-distribution.md` for the 5-vs-15-tools routing experiment.
"""
from __future__ import annotations

from mcp_server import server

# --- tool_choice builders (Anthropic Messages API shapes) -------------------


def auto() -> dict:
    """Model may call a tool or answer in text."""
    return {"type": "auto"}


def any_tool() -> dict:
    """Model MUST call some tool — a conversational text reply is not acceptable."""
    return {"type": "any"}


def force(name: str) -> dict:
    """Model MUST call exactly this tool on the next response."""
    return {"type": "tool", "name": name}


def none() -> dict:
    """Model may not call any tool."""
    return {"type": "none"}


# --- scoped narrow tool for a high-frequency need ---------------------------
# "Where's my refund/order?" is the most common request. A narrow check_refund_status
# (just the status) is selected more reliably than the general-purpose lookup_order, and
# returns a smaller payload.

CHECK_REFUND_STATUS_SCHEMA = {
    "name": "check_refund_status",
    "description": (
        "Return ONLY the current status of an order/refund by order id — nothing else. "
        "Use this for the high-frequency 'where is my order/refund?' question instead of the "
        "general lookup_order (which returns the full order)."
    ),
    "input_schema": {"type": "object",
                     "properties": {"order_id": {"type": "string"}},
                     "required": ["order_id"]},
}


def check_refund_status(order_id: str) -> dict:
    """Narrow projection over the order — returns just id + status (delegates to lookup_order
    so it inherits SA-11 validation/error handling)."""
    res = server.lookup_order(order_id)
    if res.get("ok"):
        return {"ok": True, "order_id": res["order"]["order_id"], "status": res["order"]["status"]}
    return res  # propagate not_found / structured error unchanged


# All schemas the system knows about (the 4 core tools + the scoped one).
ALL_SCHEMAS = [*server.TOOL_SCHEMAS, CHECK_REFUND_STATUS_SCHEMA]
_BY_NAME = {t["name"]: t for t in ALL_SCHEMAS}

# Per-role tool sets — each kept small (≤5) for selection reliability.
ROLE_TOOLS = {
    "verification": ["get_customer"],
    "status": ["check_refund_status"],
    "triage": ["get_customer", "lookup_order", "check_refund_status"],
    "refunds": ["get_customer", "lookup_order", "process_refund", "escalate_to_human"],
}


def tools_for(role: str) -> list[dict]:
    """The schemas a given role/subagent should receive — role-relevant tools only."""
    return [_BY_NAME[name] for name in ROLE_TOOLS[role]]


# --- constrained workflow: verification guaranteed first --------------------


def refund_workflow_steps() -> list[dict]:
    """A constrained refund flow. Each step is its own API turn (forced choice only governs
    the next response):
      1. FORCE get_customer  → verification is guaranteed to run first
      2. ANY tool            → must act (find the order), no chit-chat
      3. AUTO                → may act or explain the outcome
    """
    return [
        {"step": "verify", "tools": tools_for("verification"), "tool_choice": force("get_customer")},
        {"step": "find_order", "tools": tools_for("triage"), "tool_choice": any_tool()},
        {"step": "resolve", "tools": tools_for("refunds"), "tool_choice": auto()},
    ]
