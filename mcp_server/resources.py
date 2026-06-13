"""Policy catalog exposed as MCP resources (SA-12).

The agent reads refund/returns policy directly as MCP **resources** — no exploratory tool
calls — which keeps policy out of the tool token budget and out of the model's guesswork.
URIs are **stable** (the catalog contract); content is rendered from the same constants the
tools enforce, so the published policy and the runtime behavior never drift.
"""
from __future__ import annotations

from typing import Any

from mcp_server.backend import REFUND_AUTO_APPROVE_LIMIT

# Stable resource URIs — the catalog contract. Do not change without versioning.
REFUND_POLICY_URI = "resolvedesk://policy/refund"
RETURNS_POLICY_URI = "resolvedesk://policy/returns"

RETURN_WINDOW_DAYS = 30


def refund_policy() -> str:
    return (
        "# Refund policy\n"
        f"- Refunds up to ${REFUND_AUTO_APPROVE_LIMIT:.0f} are auto-approved.\n"
        "- Above that limit a human must approve — call escalate_to_human.\n"
        "- A refund may never exceed the order total.\n"
        "- The customer must be verified (get_customer) before any refund."
    )


def returns_policy() -> str:
    return (
        "# Returns policy\n"
        f"- Items are returnable within {RETURN_WINDOW_DAYS} days of delivery.\n"
        "- Approved returns are refunded to the original payment method after inspection.\n"
        "- Final-sale items are non-returnable."
    )


# name -> (uri, renderer); keeps the catalog introspectable for tests/docs.
POLICY_CATALOG = {
    "refund": (REFUND_POLICY_URI, refund_policy),
    "returns": (RETURNS_POLICY_URI, returns_policy),
}


def register_resources(mcp: Any) -> None:
    """Register the policy catalog on a FastMCP server as read-only resources."""
    for _name, (uri, render) in POLICY_CATALOG.items():
        mcp.resource(uri)(render)
