"""Semantic validation for extractions (SA-18) — layer 2 of three.

Layer 1 (schema, SA-17) guarantees *syntax*. This layer checks *semantics* a schema can't:
totals reconciliation (line items vs stated total), date ordering, and an `other`-without-
detail structure check. Each issue is classified **retryable** (a format/structure mistake
the model can likely fix on a second pass) vs **non-retryable** (the info is simply absent
from the source — retrying would only burn calls). `conflict_detected` flags inconsistent
source data.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from extraction.schemas import DamageReport, DamageType, Invoice, WarrantyCard


@dataclass
class ValidationIssue:
    field: str
    message: str
    retryable: bool


@dataclass
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)
    conflict_detected: bool = False

    @property
    def ok(self) -> bool:
        return not self.issues

    @property
    def retryable(self) -> bool:
        """Retry only when there are issues AND every one is retryable (no absent-info)."""
        return bool(self.issues) and all(i.retryable for i in self.issues)

    def to_feedback(self) -> str:
        return "\n".join(f"- {i.field}: {i.message}" for i in self.issues)


def _date(s: str | None) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(s)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return None


def validate_invoice(inv: Invoice) -> ValidationReport:
    issues: list[ValidationIssue] = []
    conflict = False

    # totals reconciliation: calculated_total vs stated_total
    if inv.line_items and inv.total_amount is not None:
        amounts = [li.amount for li in inv.line_items if li.amount is not None]
        if amounts:
            calculated = round(sum(amounts), 2)
            if abs(calculated - inv.total_amount) > 0.01:
                issues.append(ValidationIssue(
                    "total_amount",
                    f"line items sum to {calculated} but stated total is {inv.total_amount}",
                    retryable=True))
                conflict = True

    # date ordering: due_date must not precede invoice_date
    d_inv, d_due = _date(inv.invoice_date), _date(inv.due_date)
    if d_inv and d_due and d_due < d_inv:
        issues.append(ValidationIssue(
            "due_date", f"due_date {inv.due_date} precedes invoice_date {inv.invoice_date}",
            retryable=True))
        conflict = True

    # absent required info — NOT retryable (the document has no amount at all)
    if inv.total_amount is None and not inv.line_items:
        issues.append(ValidationIssue(
            "total_amount", "no total or line items present in the document", retryable=False))

    return ValidationReport(issues, conflict)


def validate_warranty(w: WarrantyCard) -> ValidationReport:
    issues: list[ValidationIssue] = []
    if w.warranty_months is not None and w.warranty_months <= 0:
        issues.append(ValidationIssue(
            "warranty_months", f"non-positive warranty_months {w.warranty_months}", retryable=True))
    if w.product is None and w.serial_number is None:
        issues.append(ValidationIssue(
            "product", "neither product nor serial number found in the document", retryable=False))
    return ValidationReport(issues)


def validate_damage(d: DamageReport) -> ValidationReport:
    issues: list[ValidationIssue] = []
    if d.damage_type == DamageType.OTHER and not d.damage_type_other:
        issues.append(ValidationIssue(
            "damage_type_other", "damage_type is 'other' but no detail was provided", retryable=True))
    if d.damage_type is None and d.description is None:
        issues.append(ValidationIssue(
            "damage_type", "no damage information found in the document", retryable=False))
    return ValidationReport(issues)


_VALIDATORS = {Invoice: validate_invoice, WarrantyCard: validate_warranty, DamageReport: validate_damage}


def validate(model) -> ValidationReport:
    """Dispatch to the right semantic validator for the extracted model."""
    return _VALIDATORS[type(model)](model)
