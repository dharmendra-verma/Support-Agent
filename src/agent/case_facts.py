"""Persistent case-facts context layer (SA-28).

Long support conversations have three context failure modes:
1. **progressive summarization** blurs exact amounts/dates/order numbers ("about $50");
2. the **lost-in-the-middle** effect drops facts stated in the middle of a long history;
3. a 40-field order lookup **bloats context** when 5 fields matter.

The fix is a small, authoritative **case-facts block** that is extracted from every turn and
**prepended to each request, OUTSIDE the summarized history** — so exact transactional facts
survive verbatim no matter how the rest of the history is compressed. The block is **updated
in place** (not append-only): when an order's status changes, the new status overwrites the
old one rather than accumulating a contradictory history.

The per-turn extractor here is a deterministic regex pass so the behavior is provable offline.
A model-based extractor (a single-shot Claude Messages-API call — non-agentic, so the direct
API per the two-path rule) can be injected via ``extract_fn`` for production fidelity.

Exam: D5 TS 5.1.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

# --- patterns for transactional facts ---------------------------------------

_AMOUNT_RE = re.compile(r"\$\d+(?:\.\d{2})?")
_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_ORDER_RE = re.compile(r"(?:#|order\s+#?)(\d{4,})", re.IGNORECASE)
_STATUS_RE = re.compile(
    r"\b(processing|shipped|delivered|refunded|cancell?ed|pending|returned|in transit)\b",
    re.IGNORECASE,
)
# Customer-stated expectations: a clause anchored on an intent verb, up to sentence end.
_EXPECT_RE = re.compile(r"\b((?:want|expect|need)s?\b[^.!?]*)", re.IGNORECASE)


@dataclass
class CaseFacts:
    """Authoritative transactional facts carried across every turn.

    ``orders`` is a mapping order_id -> latest status, so a status change **overwrites** (the
    block stays current, never self-contradictory). Lists are de-duplicated on insert so a
    fact mentioned repeatedly appears once.
    """

    orders: dict[str, str] = field(default_factory=dict)   # order_id -> status (updatable)
    amounts: list[str] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    expectations: list[str] = field(default_factory=list)

    def _add(self, bucket: list[str], value: str) -> None:
        if value not in bucket:
            bucket.append(value)

    def set_order_status(self, order_id: str, status: str | None) -> None:
        """Record/refresh an order's status. A later status overwrites an earlier one; an
        order seen without a status is registered as ``unknown`` until one arrives."""
        if status:
            self.orders[order_id] = status
        else:
            self.orders.setdefault(order_id, "unknown")

    def to_block(self) -> str:
        """Render the case-facts block: authoritative, with explicit section headers and the
        key facts up front (countering lost-in-the-middle). Empty sections are omitted."""
        lines = ["[CASE FACTS — authoritative; do not summarize, round, or drop these]"]
        if self.orders:
            lines.append("## Orders & statuses")
            lines.extend(f"- #{oid}: {status}" for oid, status in self.orders.items())
        if self.amounts:
            lines.append("## Amounts")
            lines.extend(f"- {a}" for a in self.amounts)
        if self.dates:
            lines.append("## Dates")
            lines.extend(f"- {d}" for d in self.dates)
        if self.expectations:
            lines.append("## Customer expectations")
            lines.extend(f"- {e}" for e in self.expectations)
        return "\n".join(lines)


# A fact extractor maps turn text -> a partial CaseFacts to merge in.
ExtractFn = Callable[[str], CaseFacts]


def extract_facts(text: str) -> CaseFacts:
    """Deterministic regex extraction of transactional facts from one turn of text."""
    facts = CaseFacts()
    order_ids = [m.group(1) for m in _ORDER_RE.finditer(text)]
    status_match = _STATUS_RE.search(text)
    status = status_match.group(1).lower() if status_match else None
    for oid in order_ids:
        facts.set_order_status(oid, status)
    for a in _AMOUNT_RE.findall(text):
        facts._add(facts.amounts, a)
    for d in _DATE_RE.findall(text):
        facts._add(facts.dates, d)
    for m in _EXPECT_RE.finditer(text):
        facts._add(facts.expectations, m.group(1).strip())
    return facts


def update_facts(facts: CaseFacts, text: str, *, extract_fn: ExtractFn | None = None) -> CaseFacts:
    """Merge the facts found in ``text`` into ``facts`` **in place** and return it.

    Statuses overwrite (update semantics); amounts/dates/expectations are de-duplicated. Runs
    once per turn. ``extract_fn`` defaults to the regex extractor; inject a model-based one for
    production.
    """
    extracted = (extract_fn or extract_facts)(text)
    for oid, status in extracted.orders.items():
        facts.set_order_status(oid, None if status == "unknown" else status)
    for a in extracted.amounts:
        facts._add(facts.amounts, a)
    for d in extracted.dates:
        facts._add(facts.dates, d)
    for e in extracted.expectations:
        facts._add(facts.expectations, e)
    return facts
