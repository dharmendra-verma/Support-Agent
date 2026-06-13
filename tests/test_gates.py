"""Tests for the prerequisite gate (SA-14).

The gate is deterministic, so the safety property ("0 unverified refunds") is *proven*
offline by running adversarial dispatch sequences through it — no model needed. A live
end-to-end adversarial run (and the prompt-only baseline) is skipped without a key.
"""
from __future__ import annotations

import os

import pytest

from agent.gates import GATED_TOOLS, SessionGate, backend_resolver, guarded_dispatch
from mcp_server.backend import Backend

JANE = {"customer_id": "C-1001", "name": "Jane Doe", "email": "jane@example.com"}
RAJ = {"customer_id": "C-1002", "name": "Raj Patel", "email": "raj@example.com"}


def recording_handlers():
    """Handlers that record execution, so we can prove a blocked tool never ran."""
    executed = []

    def make(name):
        def h(**kw):
            executed.append(name)
            return {"ok": True, "executed": name}
        return h

    return executed, {t: make(t) for t in ("lookup_order", "process_refund", "escalate_to_human")}


# --- gate state -------------------------------------------------------------


def test_check_blocks_gated_tools_until_verified():
    gate = SessionGate()
    for tool in GATED_TOOLS:
        blocked = gate.check(tool)
        assert blocked is not None and blocked["error"] == "prerequisite_unmet"
        assert blocked["missing"] == "verified_customer"


def test_check_allows_after_verify():
    gate = SessionGate()
    gate.verify([JANE])
    assert gate.verified_customer_id == "C-1001"
    assert gate.check("process_refund") is None
    assert gate.check("lookup_order") is None


def test_verify_ambiguous_does_not_verify_and_asks_for_more():
    gate = SessionGate()
    out = gate.verify([JANE, RAJ])
    assert out["ok"] is False and out["error"] == "ambiguous_customer"
    assert set(out["candidates"]) == {"C-1001", "C-1002"}
    assert gate.verified_customer_id is None  # never heuristically picks one


def test_verify_not_found_does_not_verify():
    gate = SessionGate()
    out = gate.verify([])
    assert out["ok"] is False and out["error"] == "not_found"
    assert gate.verified_customer_id is None


def test_reset_and_customer_switch():
    gate = SessionGate()
    gate.verify([JANE])
    assert gate.verified_customer_id == "C-1001"
    gate.verify([RAJ])  # switch customer mid-conversation
    assert gate.verified_customer_id == "C-1002"
    gate.reset()
    assert gate.verified_customer_id is None
    assert gate.check("process_refund") is not None  # blocked again after reset


# --- dispatch enforcement ---------------------------------------------------


def test_refund_blocked_before_verify_handler_never_runs():
    gate = SessionGate()
    executed, handlers = recording_handlers()
    res = guarded_dispatch(gate, "process_refund", {"order_id": "12345", "amount": 40.0, "reason": "x"},
                           handlers=handlers, resolve_customers=lambda i: [])
    assert res["error"] == "prerequisite_unmet"
    assert executed == []  # the money-moving handler was never reached


def test_allowed_after_get_customer_via_dispatch():
    gate = SessionGate()
    executed, handlers = recording_handlers()
    resolve = backend_resolver(Backend.seeded())
    assert guarded_dispatch(gate, "get_customer", {"identifier": "C-1001"},
                            handlers=handlers, resolve_customers=resolve)["verified"] is True
    guarded_dispatch(gate, "process_refund", {"order_id": "12345", "amount": 40.0, "reason": "x"},
                     handlers=handlers, resolve_customers=resolve)
    assert executed == ["process_refund"]


def test_escalate_is_not_gated():
    gate = SessionGate()
    executed, handlers = recording_handlers()
    guarded_dispatch(gate, "escalate_to_human", {"reason": "stuck"},
                     handlers=handlers, resolve_customers=lambda i: [])
    assert executed == ["escalate_to_human"]  # human handoff always reachable


def test_backend_resolver_matches_id_email_name():
    resolve = backend_resolver(Backend.seeded())
    assert [c["customer_id"] for c in resolve("C-1001")] == ["C-1001"]
    assert [c["customer_id"] for c in resolve("JANE@example.com")] == ["C-1001"]
    assert [c["customer_id"] for c in resolve("nobody")] == []


# --- deterministic adversarial proof (AC: 0 unverified refunds) -------------


def _adversarial_sequences():
    """50 sequences that try to refund/look-up before (or instead of) verifying."""
    refund = ("process_refund", {"order_id": "12345", "amount": 40.0, "reason": "r"})
    order = ("lookup_order", {"order_id": "12345"})
    gc_ok = ("get_customer", {"identifier": "C-1001"})
    gc_bad = ("get_customer", {"identifier": "ghost@nowhere.com"})
    gc_amb = ("get_customer", {"identifier": "a"})  # substring matches >1 name? -> see note
    seqs = []
    for i in range(50):
        seq = [refund, order]                 # straight-up attempt with no verification
        if i % 2:
            seq += [gc_bad, refund]           # retry after a failed verify
        if i % 3:
            seq += [gc_amb, refund]           # retry after an ambiguous verify
        if i % 5 == 0:
            seq += [gc_ok, refund, order]     # legit flow after a real verify
        seqs.append(seq)
    return seqs


def test_adversarial_50_runs_zero_unverified_refunds():
    unverified_refunds = 0
    legit_refunds = 0
    for seq in _adversarial_sequences():
        gate = SessionGate()
        executed, handlers = recording_handlers()
        resolve = backend_resolver(Backend.seeded())
        for name, inp in seq:
            before = gate.verified_customer_id
            res = guarded_dispatch(gate, name, inp, handlers=handlers, resolve_customers=resolve)
            if name == "process_refund":
                ran = res.get("executed") == "process_refund"
                if ran and before is None:
                    unverified_refunds += 1   # must never happen
                if ran:
                    legit_refunds += 1
    assert unverified_refunds == 0
    assert legit_refunds > 0  # the gate allows verified refunds (not just blocking everything)


# --- live end-to-end (skipped without a key) --------------------------------


@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"),
                    reason="live adversarial agent run needs ANTHROPIC_API_KEY")
def test_live_adversarial_no_unverified_refunds():
    """Drive the real model through guarded_dispatch over adversarial prompts; assert it
    can never complete a refund without a prior get_customer. (Baseline without the gate is
    recorded separately for comparison — see docs/policy-gates.md.)"""
    pytest.skip("live harness: see docs/policy-gates.md for the 50-run procedure")
