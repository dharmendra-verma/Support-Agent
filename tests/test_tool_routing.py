"""Tests for the MCP tools (SA-10).

Offline: backend lookups, handler structured results, description quality, and that the
FastMCP server registers. Live: the get_customer-vs-lookup_order routing test (≥9/10 on
ambiguous prompts) calls the real model and is skipped without ANTHROPIC_API_KEY.
"""
from __future__ import annotations

import os

import pytest

from mcp_server import server
from mcp_server.backend import Backend, NotFoundError

EXPECTED_TOOLS = {"get_customer", "lookup_order", "process_refund", "escalate_to_human"}


# --- backend ----------------------------------------------------------------


def test_backend_get_customer_by_id_and_email():
    b = Backend.seeded()
    assert b.get_customer("C-1001")["name"] == "Jane Doe"
    assert b.get_customer("JANE@example.com")["customer_id"] == "C-1001"  # case-insensitive


def test_backend_unknown_customer_and_order_raise():
    b = Backend.seeded()
    with pytest.raises(NotFoundError):
        b.get_customer("nobody@nowhere.com")
    with pytest.raises(NotFoundError):
        b.get_order("0000")


def test_backend_order_id_tolerates_hash_and_leading_space():
    b = Backend.seeded()
    assert b.get_order("#12345")["status"] == "shipped"
    assert b.get_order(" #12345 ")["status"] == "shipped"  # space before '#' too


def test_over_limit_refund_is_not_persisted():
    """Over-limit refunds need human approval and must NOT be recorded (no double-refund)."""
    b = Backend.seeded()
    over = b.record_refund("12345", 999.0, "big")
    assert over["auto_approved"] is False
    assert b.refunds == []  # nothing persisted until approved
    b.record_refund("12345", 40.0, "small")
    assert len(b.refunds) == 1  # auto-approved one is recorded


# --- handlers (structured results) ------------------------------------------


def test_handlers_return_structured_success_and_not_found():
    assert server.get_customer("C-1001")["ok"] is True
    miss = server.lookup_order("0000")
    assert miss["ok"] is False and miss["error"] == "not_found"


def test_refund_auto_approves_under_limit_and_flags_over():
    ok = server.process_refund("12345", 40.0, "damaged")
    assert ok["ok"] is True and ok["refund"]["auto_approved"] is True
    over = server.process_refund("12345", 999.0, "big")
    assert over["ok"] is False and over["error"] == "requires_approval"


def test_escalate_returns_ticket():
    out = server.escalate_to_human("refund over limit", context="order 12345")
    assert out["ok"] is True and out["ticket"]["ticket_id"].startswith("ESC-")


# --- description quality (the selection mechanism) --------------------------


def test_all_four_tools_present():
    assert {t["name"] for t in server.TOOL_SCHEMAS} == EXPECTED_TOOLS


def test_descriptions_cover_required_facets():
    for t in server.TOOL_SCHEMAS:
        d = t["description"]
        assert "Input:" in d, f"{t['name']} missing input format"
        assert "Example quer" in d, f"{t['name']} missing example"
        assert "Edge case" in d, f"{t['name']} missing edge cases"
        assert "Boundary:" in d, f"{t['name']} missing when-to-use boundary"


def test_similar_tools_cross_reference_each_other():
    """The fix for misrouting: each twin names the other as the boundary."""
    by_name = {t["name"]: t["description"] for t in server.TOOL_SCHEMAS}
    assert "lookup_order" in by_name["get_customer"]
    assert "get_customer" in by_name["lookup_order"]


def test_system_prompt_has_no_hardcoded_tool_routing():
    """Routing must come from descriptions, not keyword cues in the system prompt."""
    sp = server.SYSTEM_PROMPT.lower()
    for name in EXPECTED_TOOLS:
        assert name not in sp


def test_fastmcp_server_builds():
    srv = server.build_server()
    assert srv is not None


# --- live routing (skipped without a key) -----------------------------------

ROUTING_CASES = [
    ("Check my order #12345", "lookup_order"),
    ("What's the status of order 98765?", "lookup_order"),
    ("Has order #12345 shipped yet?", "lookup_order"),
    ("What did I buy on order A-555?", "lookup_order"),
    ("Where is order 7777 right now?", "lookup_order"),
    ("Look up the account for jane@example.com", "get_customer"),
    ("Pull up customer C-1002", "get_customer"),
    ("What tier is the account jane@example.com on?", "get_customer"),
    ("Get my profile, customer id C-1001", "get_customer"),
    ("Find the customer record for raj@example.com", "get_customer"),
]


@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"),
                    reason="live routing test needs ANTHROPIC_API_KEY")
def test_get_customer_vs_lookup_order_routing():
    import anthropic

    client = anthropic.Anthropic()
    correct = 0
    misroutes = []
    for prompt, expected in ROUTING_CASES:
        resp = client.messages.create(
            model=os.environ.get("ROUTING_MODEL", "claude-sonnet-4-6"),
            max_tokens=512,
            system=server.SYSTEM_PROMPT,
            tools=server.TOOL_SCHEMAS,
            messages=[{"role": "user", "content": prompt}],
        )
        used = next((b.name for b in resp.content if getattr(b, "type", None) == "tool_use"), None)
        if used == expected:
            correct += 1
        else:
            misroutes.append((prompt, expected, used))
    assert correct >= 9, f"routing only {correct}/10; misroutes={misroutes}"
