"""Tests for escalation criteria + structured handoff (SA-16).

The 15-case scenario suite exercises the categorical rules — including the cases that the
exam principle hinges on: frustration alone does NOT escalate, explicit human requests do
(immediately), and policy gaps do. Deterministic, so routing is provable offline.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.escalation import (
    CaseSignals,
    HandoffPayload,
    Route,
    build_handoff,
    classify_escalation,
)

E, R = Route.ESCALATE, Route.RESOLVE

# (name, signals, expected route) — 15 cases incl. policy-gap and demand-human.
SCENARIOS = [
    ("demands human", CaseSignals(explicit_human_request=True), E),
    ("demands human politely while resolvable",
     CaseSignals(explicit_human_request=True, resolvable=True), E),
    ("policy gap: refund over limit", CaseSignals(policy_gap=True), E),
    ("ambiguous undefined exception", CaseSignals(policy_gap=True, resolvable=False), E),
    ("stuck after genuine attempts", CaseSignals(no_progress=True), E),
    ("policy gap while frustrated", CaseSignals(policy_gap=True, frustrated=True), E),
    ("frustrated, reiterated after offer",
     CaseSignals(frustrated=True, customer_reiterated=True), E),
    ("easy order-status question", CaseSignals(), R),
    ("frustrated but resolvable (first time)",
     CaseSignals(frustrated=True, resolvable=True), R),
    ("angry but order lookup resolves it", CaseSignals(frustrated=True), R),
    ("low self-confidence but resolvable", CaseSignals(resolvable=True), R),
    ("refund within limit", CaseSignals(), R),
    ("made progress, can continue", CaseSignals(no_progress=False), R),
    ("frustrated, accepted the offer (no reiteration)",
     CaseSignals(frustrated=True, customer_reiterated=False), R),
    ("plain resolvable case", CaseSignals(resolvable=True, frustrated=False), R),
]


def test_all_scenarios_route_correctly():
    # The rules are deterministic, so the AC's >=90% bar is met at 100% — assert exactly
    # that, so flipping any single critical case (demand-human, policy-gap, frustration)
    # is caught instead of hidden by aggregate slack.
    wrong = [(name, classify_escalation(sig).route, expected)
             for name, sig, expected in SCENARIOS
             if classify_escalation(sig).route != expected]
    assert wrong == [], f"mis-routed {len(wrong)}/{len(SCENARIOS)}: {wrong}"


def test_frustration_alone_never_escalates():
    # frustration only — no other signal (resolvable defaults True)
    assert classify_escalation(CaseSignals(frustrated=True)).route == R


def test_explicit_request_escalates_immediately_even_if_resolvable():
    d = classify_escalation(CaseSignals(explicit_human_request=True, resolvable=True))
    assert d.route == E and "explicitly requested" in d.reason


def test_policy_gap_escalates():
    assert classify_escalation(CaseSignals(policy_gap=True)).route == E


def test_reiteration_after_offer_escalates():
    assert classify_escalation(CaseSignals(frustrated=True, customer_reiterated=True)).route == E


# --- structured handoff (Pydantic) ------------------------------------------


def test_handoff_payload_has_all_required_fields():
    p = build_handoff(
        customer_id="C-1001",
        issue_summary="wants $600 refund for damaged item on order 98765",
        root_cause="refund exceeds $500 autonomous limit",
        actions_attempted=["verified customer", "looked up order 98765"],
        recommended_action="approve one-time $600 exception",
        amounts={"refund_requested": 600.0, "order_total": 640.0},
    )
    assert p.customer_id == "C-1001"
    ctx = p.to_context()
    for token in ("C-1001", "root cause", "recommended action", "refund_requested=600"):
        assert token in ctx


def test_handoff_payload_rejects_missing_fields():
    with pytest.raises(ValidationError):
        HandoffPayload(customer_id="C-1001")  # missing summary/root_cause/etc.


# --- system prompt carries criteria + few-shot ------------------------------


def test_system_prompt_has_criteria_and_fewshot():
    text = Path("prompts/system.md").read_text(encoding="utf-8")
    # explicit triggers present, anti-triggers stated, and few-shot examples
    assert "explicitly asks for a human" in text
    assert "Never escalate" in text and "frustration" in text.lower()
    assert "Few-shot examples" in text
    assert text.lower().count("escalate") >= 4  # multiple worked examples
    assert "Handoff payload" in text
