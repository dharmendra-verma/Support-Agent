"""Multi-issue message decomposition + parallel investigation (SA-29).

Customers raise several concerns in one message ("refund my order, fix my billing, and update
my address"). Handling them as one blob silently drops items; handling them serially is slow.
This module **decomposes** a multi-concern message into distinct, individually-tracked
``Issue`` items (each with its own persisted structured facts via the SA-28 case-facts layer),
**investigates independent items in parallel** under a shared verified-customer context, and
**synthesises one unified response** — with no item dropped.

Cross-issue dependencies are detected and sequenced: a refund can't be settled before the
order's status/cancellation is known, so the refund item depends on (and runs after) those.

Exam: D1 TS 1.4, D5 TS 5.1.
"""
from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from agent.case_facts import CaseFacts, extract_facts

# --- issue kinds + intent detection -----------------------------------------

REFUND = "refund"
BILLING = "billing"
ADDRESS = "address"
CANCEL = "cancel"
ORDER_STATUS = "order_status"
RETURN = "return"
ACCOUNT = "account"
OTHER = "other"

# Ordered so the FIRST matching kind wins within a clause (more specific before generic).
_INTENT_SIGNALS: list[tuple[str, tuple[str, ...]]] = [
    (REFUND, ("refund", "money back", "my money")),
    (BILLING, ("billing", "overcharg", "double charg", "charged twice", "invoice", "payment")),
    (ADDRESS, ("address", "shipping info")),
    (CANCEL, ("cancel",)),
    (ORDER_STATUS, ("status", "where is", "track", "tracking", "delivered yet")),
    (RETURN, ("return", "exchange", "replace")),
    (ACCOUNT, ("password", "log in", "login", "my account")),
]

# Concern boundaries: commas/semicolons/sentences and listing conjunctions all separate
# distinct concerns (unlike case_facts, where commas stay within a clause). A period is a
# delimiter only as a sentence terminator — NOT a decimal point inside an amount like $49.99
# (otherwise the amount would be torn across two issues).
_CONCERN_SPLIT_RE = re.compile(
    r"[,;]|(?<!\d)\.(?!\d)|\band\b|\bbut\b|\balso\b|\bthen\b|\bplus\b", re.IGNORECASE)

# Dependency rules: a kind that cannot be actioned until another kind is resolved first.
_DEPENDS_ON_KINDS: dict[str, set[str]] = {
    REFUND: {ORDER_STATUS, CANCEL},  # must confirm the order's status / cancellation first
}

OPEN = "open"
IN_PROGRESS = "in_progress"
RESOLVED = "resolved"


@dataclass
class Issue:
    """One tracked concern: its kind, the originating text, its own structured facts (a
    separate per-issue context layer), status, and any issues it must wait on."""

    id: str
    kind: str
    description: str
    facts: CaseFacts = field(default_factory=CaseFacts)
    status: str = OPEN
    depends_on: list[str] = field(default_factory=list)


def _detect_intent(clause: str) -> str | None:
    low = clause.lower()
    for kind, signals in _INTENT_SIGNALS:
        if any(s in low for s in signals):
            return kind
    return None


def decompose_message(text: str) -> list[Issue]:
    """Split a multi-concern message into distinct ``Issue`` items.

    Each clause that carries a recognisable intent becomes one issue, with its order
    IDs/amounts/statuses extracted into the issue's own case-facts layer. Cross-issue
    dependencies (e.g. refund → order status) are linked so they can be sequenced.
    """
    issues: list[Issue] = []
    for clause in _CONCERN_SPLIT_RE.split(text):
        clause = clause.strip()
        if not clause:
            continue
        kind = _detect_intent(clause)
        if kind is None:
            continue
        issues.append(Issue(id=f"issue-{len(issues) + 1}", kind=kind, description=clause,
                            facts=extract_facts(clause)))
    _link_dependencies(issues)
    return issues


def _link_dependencies(issues: list[Issue]) -> None:
    """Wire ``depends_on`` from the kind rules — a refund waits on the order-status/cancel
    items in the same message."""
    by_kind: dict[str, list[Issue]] = defaultdict(list)
    for issue in issues:
        by_kind[issue.kind].append(issue)
    for issue in issues:
        for dep_kind in _DEPENDS_ON_KINDS.get(issue.kind, set()):
            for dep in by_kind.get(dep_kind, []):
                if dep.id != issue.id:
                    issue.depends_on.append(dep.id)


# --- ledger: per-issue tracking as a separate context layer -----------------


@dataclass
class IssueLedger:
    """The session's issue ledger — distinct from the case-facts layer. Tracks each concern's
    status so nothing is lost across a multi-step resolution."""

    issues: list[Issue] = field(default_factory=list)

    def open_issues(self) -> list[Issue]:
        return [i for i in self.issues if i.status != RESOLVED]

    def mark(self, issue_id: str, status: str) -> None:
        for i in self.issues:
            if i.id == issue_id:
                i.status = status
                return
        raise KeyError(issue_id)

    def all_resolved(self) -> bool:
        return all(i.status == RESOLVED for i in self.issues)

    def to_block(self) -> str:
        lines = ["[ISSUE LEDGER — every open concern; resolve all before closing]"]
        for i in self.issues:
            lines.append(f"- {i.id} [{i.kind}] {i.status}: {i.description}")
        return "\n".join(lines)


# --- dependency-aware sequencing into parallel layers -----------------------


def sequence(issues: list[Issue]) -> list[list[Issue]]:
    """Topologically layer issues so independent ones share a layer (run in parallel) and a
    dependent one lands in a later layer than everything it waits on. Raises on a dependency
    cycle rather than silently looping."""
    by_id = {i.id: i for i in issues}
    resolved: set[str] = set()
    layers: list[list[Issue]] = []
    remaining = list(issues)
    while remaining:
        ready = [i for i in remaining
                 if all(dep in resolved for dep in i.depends_on if dep in by_id)]
        if not ready:
            raise ValueError("dependency cycle among issues")
        layers.append(ready)
        resolved.update(i.id for i in ready)
        remaining = [i for i in remaining if i.id not in resolved]
    return layers


# --- parallel investigation + synthesis -------------------------------------

# investigate_fn(issue, customer, prior_results) -> a result string for that issue.
InvestigateFn = Callable[[Issue, dict, dict], Awaitable[str]]


async def investigate(issues: list[Issue], *, investigate_fn: InvestigateFn,
                      customer: dict, ledger: IssueLedger | None = None) -> dict[str, str]:
    """Investigate issues layer by layer: each layer's independent items run **concurrently**
    (``asyncio.gather``) under the shared verified-``customer`` context; dependent items run in
    a later layer and receive the prior results they depend on. Returns ``{issue_id: result}``.
    """
    results: dict[str, str] = {}
    for layer in sequence(issues):
        layer_results = await asyncio.gather(
            *(investigate_fn(issue, customer, results) for issue in layer))
        for issue, res in zip(layer, layer_results):
            results[issue.id] = res
            issue.status = RESOLVED
            if ledger is not None:
                ledger.mark(issue.id, RESOLVED)
    return results


def synthesize_response(issues: list[Issue], results: dict[str, str]) -> str:
    """Merge per-issue results into ONE unified response. Every issue appears — an item with no
    result is shown as still pending rather than dropped."""
    lines = ["Here's where each of your requests stands:"]
    for issue in issues:
        outcome = results.get(issue.id, "(still pending)")
        lines.append(f"- {issue.kind}: {outcome}")
    return "\n".join(lines)
