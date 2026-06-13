"""Multi-issue decomposition + parallel investigation tests (SA-29). Fully offline."""
from __future__ import annotations

import asyncio

from agent.decompose import (
    ADDRESS,
    BILLING,
    CANCEL,
    OPEN,
    ORDER_STATUS,
    REFUND,
    Issue,
    IssueLedger,
    decompose_message,
    investigate,
    sequence,
    synthesize_response,
)


def run(coro):
    return asyncio.run(coro)


# --- decomposition ----------------------------------------------------------


def test_decomposes_three_distinct_concerns():
    issues = decompose_message("Please refund my order, fix my billing, and update my address.")
    assert [i.kind for i in issues] == [REFUND, BILLING, ADDRESS]
    assert len({i.id for i in issues}) == 3   # distinct tracked items


def test_each_issue_persists_its_own_structured_facts():
    issues = decompose_message("Refund order #12345 for $49.99, and change my address.")
    refund = next(i for i in issues if i.kind == REFUND)
    address = next(i for i in issues if i.kind == ADDRESS)
    # The refund item owns the order/amount; the address item does not inherit them.
    assert refund.facts.orders == {"12345": "unknown"}
    assert refund.facts.amounts == ["$49.99"]
    assert address.facts.orders == {} and address.facts.amounts == []


def test_clause_without_intent_is_ignored():
    issues = decompose_message("Hi there! Hope you're well. Can you cancel my subscription?")
    assert [i.kind for i in issues] == [CANCEL]


# --- cross-issue dependencies ----------------------------------------------


def test_refund_depends_on_order_status():
    issues = decompose_message("What's the status of order #12345, and can I get a refund?")
    refund = next(i for i in issues if i.kind == REFUND)
    status = next(i for i in issues if i.kind == ORDER_STATUS)
    assert status.id in refund.depends_on


def test_independent_issues_have_no_dependencies():
    issues = decompose_message("Update my address and fix my billing.")
    assert all(i.depends_on == [] for i in issues)


def test_sequence_layers_dependents_after_dependencies():
    issues = decompose_message("Where is order #12345 and can I refund it, and update my address?")
    layers = sequence(issues)
    status_layer = next(n for n, layer in enumerate(layers)
                        for i in layer if i.kind == ORDER_STATUS)
    refund_layer = next(n for n, layer in enumerate(layers)
                        for i in layer if i.kind == REFUND)
    assert refund_layer > status_layer            # refund runs strictly after the status check


def test_sequence_detects_cycle():
    a = Issue("a", REFUND, "x", depends_on=["b"])
    b = Issue("b", REFUND, "y", depends_on=["a"])
    try:
        sequence([a, b])
    except ValueError:
        return
    raise AssertionError("expected a cycle to be detected")


# --- parallel investigation under shared customer context -------------------


def test_independent_issues_investigated_with_shared_customer_context():
    seen_customers = []

    async def investigate_fn(issue, customer, prior):
        seen_customers.append(customer["id"])
        return f"handled {issue.kind}"

    issues = decompose_message("Fix my billing and update my address.")
    results = run(investigate(issues, investigate_fn=investigate_fn, customer={"id": "C-1001"}))
    assert set(results.values()) == {"handled billing", "handled address"}
    assert seen_customers == ["C-1001", "C-1001"]   # shared verified-customer context


def test_dependent_issue_sees_prior_result():
    async def investigate_fn(issue, customer, prior):
        if issue.kind == ORDER_STATUS:
            return "shipped"
        if issue.kind == REFUND:
            # The refund can read the already-resolved status it depends on.
            dep_id = issue.depends_on[0]
            return f"refund ok (order was {prior[dep_id]})"
        return "done"

    issues = decompose_message("Status of order #12345 and can I refund it?")
    results = run(investigate(issues, investigate_fn=investigate_fn, customer={"id": "C-1"}))
    refund = next(i for i in issues if i.kind == REFUND)
    assert results[refund.id] == "refund ok (order was shipped)"


# --- ledger -----------------------------------------------------------------


def test_ledger_tracks_status_and_resolves():
    issues = decompose_message("Refund my order and update my address.")
    ledger = IssueLedger(issues=issues)
    assert len(ledger.open_issues()) == 2
    assert all(i.status == OPEN for i in issues)

    async def investigate_fn(issue, customer, prior):
        return "ok"

    run(investigate(issues, investigate_fn=investigate_fn, customer={"id": "C"}, ledger=ledger))
    assert ledger.all_resolved()
    assert ledger.open_issues() == []
    assert "ISSUE LEDGER" in ledger.to_block()


# --- synthesis: no item dropped ---------------------------------------------


def test_synthesis_mentions_every_issue():
    issues = decompose_message("Refund my order, fix my billing, and update my address.")
    results = {i.id: "done" for i in issues}
    response = synthesize_response(issues, results)
    for kind in (REFUND, BILLING, ADDRESS):
        assert kind in response


def test_synthesis_marks_unresolved_item_pending_not_dropped():
    issues = decompose_message("Refund my order and update my address.")
    # Only one resolved; the other must still appear (as pending), never dropped.
    partial = {issues[0].id: "done"}
    response = synthesize_response(issues, partial)
    assert "still pending" in response
    assert response.count("- ") == 2   # both items present


# --- 10-case no-drop set ----------------------------------------------------

_TEN_CASES = [
    ("Refund my order and fix my billing.", 2),
    ("Cancel order #12345, refund me $49.99, and update my address.", 3),
    ("Where is order #98765 and can I get a refund?", 2),
    ("Update my address, change my password, and fix my billing.", 3),
    ("I want a refund.", 1),
    ("Track order #555 and return order #556.", 2),
    ("Fix my billing, also cancel my subscription.", 2),
    ("Refund order #1 for $10, refund order #2 for $20, and update my address.", 3),
    ("My account is locked and I was overcharged on my last invoice.", 2),
    ("Cancel my order, refund my money, return the damaged item, and change my address.", 4),
]


def test_no_item_dropped_across_ten_multi_concern_cases():
    async def investigate_fn(issue, customer, prior):
        return f"resolved {issue.id}"

    for message, expected_count in _TEN_CASES:
        issues = decompose_message(message)
        assert len(issues) == expected_count, f"wrong count for: {message!r}"
        results = run(investigate(issues, investigate_fn=investigate_fn, customer={"id": "C"}))
        # Every decomposed issue is investigated AND appears in the unified response.
        assert len(results) == expected_count
        response = synthesize_response(issues, results)
        assert response.count("- ") == expected_count
