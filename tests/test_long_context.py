"""Long-context case-facts + trimming tests (SA-28). Fully offline.

Covers: per-turn fact extraction, in-place status UPDATE (not append), the case-facts block
layout, tool-output trimming with measured savings, key-summary-first assembly, and the
20-turn recall test that fails WITHOUT the layer (baseline kept as evidence) and passes with.
"""
from __future__ import annotations

from agent.case_facts import CaseFacts, extract_facts, update_facts
from agent.trimming import assemble_context, estimate_tokens, trim_output, trim_savings


# --- per-turn extraction ----------------------------------------------------


def test_extract_amounts_dates_orders_statuses():
    facts = extract_facts("Refund of $49.99 for order #12345 placed 2026-01-02, now processing.")
    assert facts.amounts == ["$49.99"]
    assert facts.dates == ["2026-01-02"]
    assert facts.orders == {"12345": "processing"}


def test_extract_customer_expectation():
    facts = extract_facts("I want the refund completed by Friday at the latest.")
    assert facts.expectations and "want the refund completed by Friday" in facts.expectations[0]


# --- update semantics: statuses overwrite, not append -----------------------


def test_status_change_overwrites_not_appends():
    facts = CaseFacts()
    update_facts(facts, "order #12345 is processing")
    update_facts(facts, "good news, order #12345 has now shipped")
    # One entry for the order, holding the LATEST status — no contradictory history.
    assert facts.orders == {"12345": "shipped"}


def test_repeated_amount_is_not_duplicated():
    facts = CaseFacts()
    update_facts(facts, "the charge was $49.99")
    update_facts(facts, "to confirm, $49.99 will be refunded")
    assert facts.amounts == ["$49.99"]


def test_each_order_gets_its_own_clause_status():
    # One status must NOT be smeared across every order in the turn.
    facts = extract_facts("Order #12345 shipped but order #67890 is pending.")
    assert facts.orders == {"12345": "shipped", "67890": "pending"}


def test_order_seen_without_status_is_unknown_until_known():
    facts = CaseFacts()
    update_facts(facts, "I'm calling about order #98765")
    assert facts.orders == {"98765": "unknown"}
    update_facts(facts, "order #98765 was delivered")
    assert facts.orders == {"98765": "delivered"}


# --- facts block layout -----------------------------------------------------


def test_facts_block_has_headers_and_is_authoritative():
    facts = CaseFacts(orders={"12345": "shipped"}, amounts=["$49.99"], dates=["2026-01-02"],
                      expectations=["wants refund by Friday"])
    block = facts.to_block()
    assert "authoritative" in block
    assert "## Orders & statuses" in block and "#12345: shipped" in block
    assert "## Amounts" in block and "$49.99" in block
    assert block.index("Orders") < block.index("Amounts")  # key facts lead


# --- tool-output trimming with measured savings -----------------------------


def _fat_order():
    # A 40-field order lookup; only a few fields are relevant.
    return {f"field_{i}": f"value_{i}" for i in range(40)} | {
        "order_id": "12345", "status": "shipped", "total": "$49.99"}


def test_trim_keeps_only_relevant_fields():
    trimmed = trim_output(_fat_order(), ["order_id", "status", "total", "missing_field"])
    assert trimmed == {"order_id": "12345", "status": "shipped", "total": "$49.99"}
    assert "field_0" not in trimmed  # the 40 irrelevant fields are gone


def test_trim_savings_are_measured_and_positive():
    full = _fat_order()
    trimmed = trim_output(full, ["order_id", "status", "total"])
    savings = trim_savings(full, trimmed)
    assert savings["after_tokens"] < savings["before_tokens"]
    assert savings["saved_tokens"] > 0 and savings["pct_saved"] > 0


# --- assembly: key summaries first ------------------------------------------


def test_assemble_puts_case_facts_first_with_headers():
    block = CaseFacts(orders={"12345": "shipped"}).to_block()
    ctx = assemble_context(block, [("Conversation summary", "earlier the customer called in")])
    assert ctx.index("CASE FACTS") < ctx.index("Conversation summary")
    assert "## Conversation summary" in ctx


# --- 20-turn recall: failing baseline vs the layer --------------------------


def _conversation():
    """20+ turns. Turn 2 states exact figures; turns 3-20 are unrelated chatter."""
    turns = [
        "Agent: Hello, how can I help?",
        "Customer: I need a refund of $49.99 for order #12345, placed 2026-01-02.",
    ]
    turns += [f"Customer: (turn {i}) also, here is some more unrelated context." for i in range(3, 22)]
    return turns


def _summarized_history(turns, *, keep_last=3):
    """Simulate progressive summarization + lost-in-the-middle: keep only the last few turns
    verbatim; everything older collapses to a generic blurb that DROPS exact figures."""
    head = "Earlier: the customer contacted support about an order and a refund."
    tail = "\n".join(turns[-keep_last:])
    return head + "\n" + tail


def test_baseline_without_layer_loses_exact_figure_from_turn_2():
    turns = _conversation()
    # Exercise the REAL assembly path with an EMPTY facts block (no layer) — only the
    # summarized history reaches the model at turn 20.
    baseline = assemble_context("", [("Conversation summary", _summarized_history(turns))])
    # Evidence of the failure mode: the exact amount/order from turn 2 are gone, and
    # assemble_context did not somehow resurrect them.
    assert "$49.99" not in baseline
    assert "#12345" not in baseline


def test_case_facts_layer_recalls_exact_figure_at_turn_20():
    turns = _conversation()
    facts = CaseFacts()
    for turn in turns:                      # extractor runs every turn
        update_facts(facts, turn)
    # The assembled context = authoritative facts block + the same summarized history.
    ctx = assemble_context(facts.to_block(),
                           [("Conversation summary", _summarized_history(turns))])
    # At turn 20 the exact turn-2 figures are still present — verbatim, not blurred.
    assert "$49.99" in ctx
    assert "#12345" in ctx
    assert "2026-01-02" in ctx


def test_estimate_tokens_monotonic():
    assert estimate_tokens("a" * 40) > estimate_tokens("a" * 4)
