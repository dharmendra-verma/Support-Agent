"""Tests for the policy/normalization hooks (SA-15).

Unit (isolation) + integration (in a dispatch loop). The hooks are deterministic, so the
"100% of attempts blocked" property is proven by a 30-run loop with no model needed.
"""
from __future__ import annotations

import asyncio

from agent.hooks import (
    REFUND_LIMIT,
    hooked_dispatch,
    normalize_result,
    post_tool_use_hook,
    pre_tool_use_hook,
    refund_threshold_decision,
)


# --- PreToolUse: refund threshold (unit) ------------------------------------


def test_refund_under_limit_allowed():
    assert refund_threshold_decision("process_refund", {"amount": 100.0}).allow is True


def test_refund_at_limit_allowed():
    assert refund_threshold_decision("process_refund", {"amount": REFUND_LIMIT}).allow is True


def test_refund_over_limit_denied_and_redirects():
    d = refund_threshold_decision("process_refund", {"amount": 750.0})
    assert d.allow is False
    assert d.redirect == "escalate_to_human"
    assert "exceeds" in d.reason


def test_non_refund_tools_not_gated():
    assert refund_threshold_decision("lookup_order", {"order_id": "12345"}).allow is True


# --- PostToolUse: normalization (unit, lossless) ----------------------------


def test_normalize_epoch_to_iso_lossless():
    out = normalize_result({"ordered_at": 1700000000})
    assert out["ordered_at"].startswith("2023-11-14")
    assert out["ordered_at"].endswith("+00:00")
    assert out["raw"]["ordered_at"] == 1700000000  # original preserved


def test_normalize_numeric_status_to_canonical_lossless():
    out = normalize_result({"status": 2})
    assert out["status"] == "shipped"
    assert out["raw"]["status"] == 2


def test_normalize_variant_status_strings():
    assert normalize_result({"status": "SHIP"})["status"] == "shipped"
    assert normalize_result({"status": "canceled"})["status"] == "cancelled"


def test_normalize_nested_order_record():
    out = normalize_result({"ok": True, "order": {"status": 3, "shipped_at": 1700000000}})
    assert out["order"]["status"] == "delivered"
    assert out["order"]["shipped_at"].startswith("2023-11-14")
    assert out["order"]["raw"]["status"] == 3


def test_normalize_passthrough_for_already_canonical_and_non_dict():
    assert normalize_result({"status": "shipped"}) == {"status": "shipped"}  # no raw churn
    assert normalize_result("not a dict") == "not a dict"


def test_normalize_does_not_touch_unrelated_numbers():
    out = normalize_result({"total": 120.0, "amount": 40})
    assert out == {"total": 120.0, "amount": 40}  # only timestamp/status fields normalized


def test_normalize_survives_preexisting_nondict_raw():
    """A tool result using 'raw' as a non-dict field must not crash normalization."""
    out = normalize_result({"status": 2, "raw": "preexisting"})
    assert out["status"] == "shipped"
    assert out["raw"]["status"] == 2  # our originals stored without TypeError


# --- integration: hooks in the dispatch loop --------------------------------


def make_handlers():
    executed = []

    def refund(**kw):
        executed.append("process_refund")
        return {"ok": True, "refund": {"amount": kw["amount"]}}

    def order(**kw):
        executed.append("lookup_order")
        return {"ok": True, "order": {"order_id": kw["order_id"], "status": 2, "ordered_at": 1700000000}}

    return executed, {"process_refund": refund, "lookup_order": order}


def test_hooked_dispatch_blocks_over_limit_handler_never_runs():
    executed, handlers = make_handlers()
    res = hooked_dispatch("process_refund", {"order_id": "12345", "amount": 999.0, "reason": "x"},
                          handlers=handlers)
    assert res["error"] == "blocked_by_policy" and res["redirect"] == "escalate_to_human"
    assert executed == []  # the money-moving handler never ran


def test_hooked_dispatch_runs_and_normalizes_under_limit():
    executed, handlers = make_handlers()
    out = hooked_dispatch("lookup_order", {"order_id": "12345"}, handlers=handlers)
    assert executed == ["lookup_order"]
    assert out["order"]["status"] == "shipped"               # PostToolUse normalized
    assert out["order"]["ordered_at"].startswith("2023-11-14")


def test_30_run_threshold_blocks_100_percent():
    """Deterministic policy → 0 over-limit refunds executed across 30 attempts."""
    leaked = 0
    for i in range(30):
        executed, handlers = make_handlers()
        amount = 500.0 + i + 1  # always over the $500 limit
        res = hooked_dispatch("process_refund", {"order_id": "12345", "amount": amount, "reason": "r"},
                              handlers=handlers)
        if res.get("ok") or executed:
            leaked += 1
    assert leaked == 0


# --- SDK hook adapters (decision wiring) ------------------------------------


def test_pre_hook_blocks_over_limit():
    out = asyncio.run(pre_tool_use_hook({"tool_name": "process_refund", "tool_input": {"amount": 999}}))
    assert out["decision"] == "block" and out["redirect"] == "escalate_to_human"


def test_pre_hook_allows_under_limit():
    out = asyncio.run(pre_tool_use_hook({"tool_name": "process_refund", "tool_input": {"amount": 10}}))
    assert out == {}


def test_post_hook_normalizes_tool_response():
    out = asyncio.run(post_tool_use_hook({"tool_response": {"status": 2}}))
    assert out["updated_tool_result"]["status"] == "shipped"
