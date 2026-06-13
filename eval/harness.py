"""Scenario runner + metrics (SA-30).

The harness drives a scripted **customer simulator** (the scenario's turns) against an injected
``agent_fn`` and records what happened, then scores the whole suite against ground truth into
the metrics Week-4 iteration needs:

* **first-contact-resolution rate** — of the requests that *should* be resolvable, how many were
  resolved on first contact;
* **correct-escalation rate (both directions)** — a confusion matrix over should-escalate vs
  did-escalate, surfacing BOTH false escalations and missed escalations;
* **tool-routing accuracy** — did the agent route the expected tools;
* **extraction accuracy by document type AND field** — reusing the SA-20 segmented report.

``agent_fn`` is injected so the harness runs offline against a fake agent; a real ``agent_fn``
would drive the SDK agent through the scripted turns.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from extraction.confidence import accuracy_report, worst_segments

from .scenarios import Scenario, load_scenarios


@dataclass
class AgentOutcome:
    """What the agent did on one scenario (the observable result the harness scores)."""

    resolved: bool
    escalated: bool
    tools_used: tuple[str, ...] = ()
    final_response: str = ""
    # extraction results: (doc_type, field, correct) — `correct` is the agent's accuracy.
    extractions: tuple[tuple[str, str, bool], ...] = ()


# An agent under test: given a scenario, drive its turns and report the outcome.
AgentFn = Callable[[Scenario], AgentOutcome]


@dataclass
class ScenarioResult:
    scenario: Scenario
    outcome: AgentOutcome

    @property
    def resolution_correct(self) -> bool:
        return self.outcome.resolved == self.scenario.expect_resolved

    @property
    def escalation_correct(self) -> bool:
        return self.outcome.escalated == self.scenario.expect_escalated

    @property
    def tools_correct(self) -> bool | None:
        """Did the agent route the expected tools (expected ⊆ used)? Returns ``None`` for a
        scenario with no tool expectation — NOT ``True`` (an empty set is vacuously a subset,
        which would inflate accuracy for a direct caller). ``compute_metrics`` skips ``None``."""
        if not self.scenario.expected_tools:
            return None
        return set(self.scenario.expected_tools).issubset(set(self.outcome.tools_used))


def run_scenario(scenario: Scenario, agent_fn: AgentFn) -> ScenarioResult:
    return ScenarioResult(scenario=scenario, outcome=agent_fn(scenario))


def run_suite(agent_fn: AgentFn, scenarios: list[Scenario] | None = None) -> list[ScenarioResult]:
    """Run every scenario end-to-end through ``agent_fn``. An explicit empty list runs nothing
    (it is NOT treated as 'use the default suite' — only ``None`` means that)."""
    chosen = scenarios if scenarios is not None else load_scenarios()
    return [run_scenario(s, agent_fn) for s in chosen]


@dataclass
class Metrics:
    total: int
    fcr_rate: float
    # escalation confusion matrix
    escalation_tp: int          # should escalate AND did
    escalation_fp: int          # should NOT escalate but did (over-escalation)
    escalation_fn: int          # should escalate but did NOT (missed)
    escalation_tn: int
    tool_routing_accuracy: float
    extraction_accuracy: dict = field(default_factory=dict)   # (doc_type, field) -> {acc, n}
    by_category: dict = field(default_factory=dict)

    @property
    def correct_escalation_rate(self) -> float:
        decided = self.escalation_tp + self.escalation_fp + self.escalation_fn + self.escalation_tn
        return (self.escalation_tp + self.escalation_tn) / decided if decided else 0.0

    @property
    def missed_escalation_rate(self) -> float:
        relevant = self.escalation_tp + self.escalation_fn
        return self.escalation_fn / relevant if relevant else 0.0

    @property
    def false_escalation_rate(self) -> float:
        negatives = self.escalation_fp + self.escalation_tn
        return self.escalation_fp / negatives if negatives else 0.0

    def worst_extraction_segments(self) -> list:
        return worst_segments(self.extraction_accuracy)


def _rate(num: int, den: int) -> float:
    return num / den if den else 0.0


def compute_metrics(results: list[ScenarioResult]) -> Metrics:
    """Aggregate scored results into the suite metrics (both escalation directions reported)."""
    total = len(results)

    # First-contact resolution: only over scenarios that SHOULD be resolvable.
    resolvable = [r for r in results if r.scenario.expect_resolved]
    fcr = _rate(sum(r.outcome.resolved for r in resolvable), len(resolvable))

    tp = fp = fn = tn = 0
    for r in results:
        should, did = r.scenario.expect_escalated, r.outcome.escalated
        if should and did:
            tp += 1
        elif not should and did:
            fp += 1
        elif should and not did:
            fn += 1
        else:
            tn += 1

    # Tool routing: only scenarios that declare expected tools.
    with_tools = [r for r in results if r.scenario.expected_tools]
    tool_acc = _rate(sum(r.tools_correct for r in with_tools), len(with_tools))

    # Extraction accuracy by (doc_type, field), reusing the SA-20 segmented report.
    records = [{"doc_type": dt, "field": fld, "correct": ok}
               for r in results for (dt, fld, ok) in r.outcome.extractions]
    extraction = accuracy_report(records) if records else {}

    by_category: dict[str, dict] = {}
    cats = {r.scenario.category for r in results}
    for cat in cats:
        crs = [r for r in results if r.scenario.category == cat]
        by_category[cat] = {
            "n": len(crs),
            "resolution_correct": _rate(sum(r.resolution_correct for r in crs), len(crs)),
            "escalation_correct": _rate(sum(r.escalation_correct for r in crs), len(crs)),
        }

    return Metrics(total=total, fcr_rate=fcr, escalation_tp=tp, escalation_fp=fp,
                   escalation_fn=fn, escalation_tn=tn, tool_routing_accuracy=tool_acc,
                   extraction_accuracy=extraction, by_category=by_category)
