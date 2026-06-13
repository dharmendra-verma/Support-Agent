"""Semantic validation + retry-loop tests (SA-18). Fully offline — the model call is
injected, so retry classification / early-exit / dead-letter are deterministic.
"""
from __future__ import annotations

from pathlib import Path

from extraction import retry
from extraction.schemas import DamageReport, Invoice, LineItem
from extraction.validate import validate, validate_invoice


# --- semantic validators ----------------------------------------------------


def test_totals_reconciliation_flags_conflict_retryable():
    inv = Invoice(total_amount=100.0,
                  line_items=[LineItem(amount=40.0), LineItem(amount=50.0)])  # sums to 90
    rep = validate_invoice(inv)
    assert not rep.ok and rep.conflict_detected
    assert rep.retryable and rep.issues[0].field == "total_amount"


def test_totals_reconcile_when_matching():
    inv = Invoice(total_amount=90.0, line_items=[LineItem(amount=40.0), LineItem(amount=50.0)])
    assert validate_invoice(inv).ok


def test_date_ordering_flags_due_before_invoice():
    rep = validate_invoice(Invoice(invoice_date="2026-02-10", due_date="2026-02-01",
                                   total_amount=10.0))
    assert rep.conflict_detected and rep.retryable


def test_absent_total_is_non_retryable():
    rep = validate_invoice(Invoice(vendor="Acme"))  # no total, no line items
    assert not rep.ok and not rep.retryable  # absent info — don't retry


def test_validate_dispatches_by_type():
    rep = validate(DamageReport(damage_type="other"))  # other without detail
    assert not rep.ok and rep.retryable


# --- retry loop -------------------------------------------------------------


def test_retryable_failure_succeeds_on_retry():
    # attempt 0: totals mismatch (retryable); attempt 1: corrected
    def extract_fn(doc, attempt, feedback):
        if attempt == 0:
            return Invoice(total_amount=100.0, line_items=[LineItem(amount=40.0)])
        assert feedback and "line items sum" in feedback  # feedback carried the error
        return Invoice(total_amount=40.0, line_items=[LineItem(amount=40.0)])

    out = retry.run_extraction("doc", extract_fn=extract_fn)
    assert out.status == retry.OK and out.attempts == 2


def test_non_retryable_exits_early_without_burning_retries():
    calls = []

    def extract_fn(doc, attempt, feedback):
        calls.append(attempt)
        return Invoice(vendor="Acme")  # absent total — non-retryable

    out = retry.run_extraction("doc", extract_fn=extract_fn, max_retries=2)
    assert out.status == retry.ABSENT_INFO and out.attempts == 1
    assert calls == [0]  # only one call — no retries burned
    assert out.reason


def test_dead_letter_after_max_retries():
    def extract_fn(doc, attempt, feedback):
        return Invoice(total_amount=100.0, line_items=[LineItem(amount=1.0)])  # always mismatched

    out = retry.run_extraction("doc", extract_fn=extract_fn, max_retries=2)
    assert out.status == retry.DEAD_LETTER and out.attempts == 3  # initial + 2 retries
    assert "max retries" in out.reason


def test_feedback_includes_document_and_failed_extraction():
    inv = Invoice(total_amount=100.0, line_items=[LineItem(amount=40.0)])
    fb = retry.build_feedback("ORIGINAL DOC TEXT", inv, validate_invoice(inv))
    assert "ORIGINAL DOC TEXT" in fb
    assert "line items sum" in fb
    assert "100" in fb  # the failed extraction is included


# --- few-shot pack ----------------------------------------------------------


def test_fewshot_pack_has_2_to_4_examples():
    text = Path("prompts/extraction_fewshot.md").read_text(encoding="utf-8")
    assert 2 <= text.count("### Example") <= 4
    assert "use null" in text.lower() and "other" in text and "unclear" in text
