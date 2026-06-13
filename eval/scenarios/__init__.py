"""Scenario suite for the evaluation harness (SA-30).

≥30 scripted conversations across five categories. Each scenario declares the *expected*
outcome (resolved-on-first-contact, escalation, the tools that should be routed, and any
document-extraction labels) so the harness can score the agent against ground truth.

Categories:
* ``standard``        — a single, in-policy request the agent should resolve directly.
* ``multi_concern``   — several concerns in one message; all should be handled.
* ``policy_gap``      — no policy covers it → the agent must escalate (not fabricate).
* ``demand_human``    — the customer explicitly demands a person → escalate.
* ``error_injection`` — a backend failure → graceful handoff, never a fake success.
"""
from __future__ import annotations

from dataclasses import dataclass

STANDARD = "standard"
MULTI_CONCERN = "multi_concern"
POLICY_GAP = "policy_gap"
DEMAND_HUMAN = "demand_human"
ERROR_INJECTION = "error_injection"

CATEGORIES = (STANDARD, MULTI_CONCERN, POLICY_GAP, DEMAND_HUMAN, ERROR_INJECTION)


@dataclass(frozen=True)
class Scenario:
    """One scripted conversation + its ground-truth expectations."""

    id: str
    category: str
    customer_turns: tuple[str, ...]
    expect_resolved: bool
    expect_escalated: bool
    expected_tools: tuple[str, ...] = ()
    # Optional document-extraction ground truth: each {doc_type, field, correct?} — the
    # `correct` is filled by the agent run; here we carry doc_type/field as the labels.
    extraction_fields: tuple[tuple[str, str], ...] = ()  # (doc_type, field)


def _s(sid, category, turns, *, resolved, escalated, tools=(), extraction=()):
    return Scenario(id=sid, category=category, customer_turns=tuple(turns),
                    expect_resolved=resolved, expect_escalated=escalated,
                    expected_tools=tuple(tools), extraction_fields=tuple(extraction))


# --- standard (8) -----------------------------------------------------------
_STANDARD = [
    _s("std-1", STANDARD, ["Where is my order #12345?"], resolved=True, escalated=False,
       tools=["lookup_order"]),
    _s("std-2", STANDARD, ["I'd like a refund of $30 on order #12345."], resolved=True,
       escalated=False, tools=["get_customer", "lookup_order", "process_refund"]),
    _s("std-3", STANDARD, ["Can you update my shipping address to 5 Oak St?"], resolved=True,
       escalated=False, tools=["get_customer"]),
    _s("std-4", STANDARD, ["What's the status of my refund for order #98765?"], resolved=True,
       escalated=False, tools=["check_refund_status"]),
    _s("std-5", STANDARD, ["Track order #555 please."], resolved=True, escalated=False,
       tools=["lookup_order"]),
    _s("std-6", STANDARD, ["I was charged but want to confirm the amount on order #12345."],
       resolved=True, escalated=False, tools=["lookup_order"]),
    _s("std-7", STANDARD, ["Please cancel order #777, it hasn't shipped."], resolved=True,
       escalated=False, tools=["lookup_order"]),
    _s("std-8", STANDARD, ["Refund $15 for order #321, it arrived damaged."], resolved=True,
       escalated=False, tools=["get_customer", "lookup_order", "process_refund"],
       extraction=[("damage_report", "damage_type"), ("damage_report", "severity")]),
]

# --- multi-concern (6) ------------------------------------------------------
_MULTI = [
    _s("multi-1", MULTI_CONCERN, ["Refund order #12345 and update my address."], resolved=True,
       escalated=False, tools=["get_customer", "lookup_order", "process_refund"]),
    _s("multi-2", MULTI_CONCERN, ["Where is order #555, and can you fix my billing?"],
       resolved=True, escalated=False, tools=["lookup_order"]),
    _s("multi-3", MULTI_CONCERN, ["Cancel #12345, refund me $20, and change my address."],
       resolved=True, escalated=False, tools=["get_customer", "lookup_order", "process_refund"]),
    _s("multi-4", MULTI_CONCERN, ["Track #1, return #2, and update my email."], resolved=True,
       escalated=False, tools=["lookup_order"]),
    _s("multi-5", MULTI_CONCERN, ["Refund $10 on #1 and $20 on #2."], resolved=True,
       escalated=False, tools=["get_customer", "lookup_order", "process_refund"]),
    _s("multi-6", MULTI_CONCERN, ["Fix my billing and confirm my order #888 status."],
       resolved=True, escalated=False, tools=["lookup_order"]),
]

# --- policy-gap → must escalate (5) -----------------------------------------
_POLICY = [
    _s("gap-1", POLICY_GAP, ["I want a refund of $5000 on order #12345."], resolved=False,
       escalated=True, tools=["get_customer", "lookup_order", "escalate_to_human"]),
    _s("gap-2", POLICY_GAP, ["Refund me for an order I placed three years ago."], resolved=False,
       escalated=True, tools=["escalate_to_human"]),
    _s("gap-3", POLICY_GAP, ["I want compensation for emotional distress."], resolved=False,
       escalated=True, tools=["escalate_to_human"]),
    _s("gap-4", POLICY_GAP, ["Waive your return policy entirely for me."], resolved=False,
       escalated=True, tools=["escalate_to_human"]),
    _s("gap-5", POLICY_GAP, ["Give me a refund AND let me keep the item, every time."],
       resolved=False, escalated=True, tools=["escalate_to_human"]),
]

# --- demand-human → escalate (5) --------------------------------------------
_HUMAN = [
    _s("human-1", DEMAND_HUMAN, ["Stop. I want to talk to a real person now."], resolved=False,
       escalated=True, tools=["escalate_to_human"]),
    _s("human-2", DEMAND_HUMAN, ["Get me your manager."], resolved=False, escalated=True,
       tools=["escalate_to_human"]),
    _s("human-3", DEMAND_HUMAN, ["I don't trust bots, transfer me to a human."], resolved=False,
       escalated=True, tools=["escalate_to_human"]),
    _s("human-4", DEMAND_HUMAN, ["This is unacceptable, escalate to a supervisor."],
       resolved=False, escalated=True, tools=["escalate_to_human"]),
    _s("human-5", DEMAND_HUMAN, ["No AI please — a person, immediately."], resolved=False,
       escalated=True, tools=["escalate_to_human"]),
]

# --- error-injection → graceful handoff (6) ---------------------------------
_ERROR = [
    _s("err-1", ERROR_INJECTION, ["Where is order #12345? [backend down]"], resolved=False,
       escalated=True, tools=["lookup_order", "escalate_to_human"]),
    _s("err-2", ERROR_INJECTION, ["Refund order #12345 [refund service timeout]"],
       resolved=False, escalated=True, tools=["lookup_order", "escalate_to_human"]),
    _s("err-3", ERROR_INJECTION, ["Look up my account [auth provider unavailable]"],
       resolved=False, escalated=True, tools=["get_customer", "escalate_to_human"]),
    _s("err-4", ERROR_INJECTION, ["Status of #555 [database error]"], resolved=False,
       escalated=True, tools=["lookup_order", "escalate_to_human"]),
    _s("err-5", ERROR_INJECTION, ["Process my refund [permission denied]"], resolved=False,
       escalated=True, tools=["process_refund", "escalate_to_human"]),
    _s("err-6", ERROR_INJECTION, ["Cancel order #777 [service unreachable]"], resolved=False,
       escalated=True, tools=["lookup_order", "escalate_to_human"]),
]

SCENARIOS: tuple[Scenario, ...] = tuple(_STANDARD + _MULTI + _POLICY + _HUMAN + _ERROR)


def load_scenarios(category: str | None = None) -> list[Scenario]:
    """All scenarios, or just those in one category."""
    if category is None:
        return list(SCENARIOS)
    return [s for s in SCENARIOS if s.category == category]
