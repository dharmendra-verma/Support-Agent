"""Independent LLM-as-judge for resolution quality (SA-30).

A separate Claude instance — given **only the transcript and the rubric**, with **no
generation context** (it never sees the agent's internal reasoning) — scores each conversation.
Judge consistency is the risk, so the rubric is **explicit pass/fail criteria with examples**,
never a vague "rate this 1-10": each criterion states exactly what passes and what fails, and
the judge returns a boolean per criterion plus a one-line justification.

The default judge here is a deterministic stand-in so the harness scores offline; a real judge
is injected via ``judge_fn`` and would issue a single-shot Claude Messages-API call (non-agentic
→ direct API per the two-path rule) built from ``build_judge_prompt``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .harness import ScenarioResult


@dataclass(frozen=True)
class Criterion:
    """One rubric criterion: an id, what PASSES, and what FAILS — with a concrete example each
    so two judges interpret it the same way."""

    key: str
    passes_when: str
    fails_when: str
    example_pass: str
    example_fail: str


RUBRIC: tuple[Criterion, ...] = (
    Criterion(
        "addressed_all_concerns",
        passes_when="every distinct concern in the customer's message gets a response",
        fails_when="any concern is ignored or silently dropped",
        example_pass="customer asks refund+address; reply covers both",
        example_fail="customer asks refund+address; reply only mentions the refund",
    ),
    Criterion(
        "no_fabrication",
        passes_when="the reply states only policy/values it can support; unknowns are deferred",
        fails_when="the reply invents a policy, amount, status, or date",
        example_pass="'I can't confirm that—escalating to a specialist.'",
        example_fail="'Your refund of $500 was approved' when no such approval exists",
    ),
    Criterion(
        "correct_handoff",
        passes_when="it escalates exactly when the case needs a human and not otherwise",
        fails_when="it resolves something it should escalate, or escalates a routine request",
        example_pass="demand-for-human → handed to an agent",
        example_fail="$5000 out-of-policy refund silently approved",
    ),
    Criterion(
        "accurate_facts",
        passes_when="order numbers/amounts cited match what the customer/tools provided",
        fails_when="a cited figure contradicts the source",
        example_pass="cites #12345 / $30 exactly as given",
        example_fail="customer said #12345 but reply cites #54321",
    ),
)


@dataclass
class RubricScore:
    """Per-criterion verdicts + an overall pass (all criteria must pass)."""

    verdicts: dict[str, bool] = field(default_factory=dict)
    justifications: dict[str, str] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return bool(self.verdicts) and all(self.verdicts.values())

    @property
    def score(self) -> float:
        """Fraction of criteria passed (for aggregate quality, not a vague 1-10)."""
        return sum(self.verdicts.values()) / len(self.verdicts) if self.verdicts else 0.0


def build_judge_prompt(result: ScenarioResult) -> str:
    """Assemble the judge prompt from ONLY the transcript + outcome + rubric — deliberately no
    agent-internal context, so the judge is independent."""
    s, o = result.scenario, result.outcome
    lines = ["You are an INDEPENDENT support-quality judge. You did not write this reply.",
             "Score the conversation against each rubric criterion as PASS or FAIL with a "
             "one-line reason. Do not invent context beyond the transcript.",
             "",
             "## Transcript",
             "Customer: " + " | ".join(s.customer_turns),
             f"Agent (resolved={o.resolved}, escalated={o.escalated}): {o.final_response}",
             "",
             "## Rubric"]
    for c in RUBRIC:
        lines.append(f"- {c.key}: PASS when {c.passes_when}; FAIL when {c.fails_when}. "
                     f"(e.g. pass: {c.example_pass}; fail: {c.example_fail})")
    return "\n".join(lines)


# A judge maps a built prompt -> {criterion_key: (verdict_bool, justification)}.
JudgeFn = Callable[[str], dict]


def _default_judge(result: ScenarioResult) -> RubricScore:
    """Deterministic stand-in judge: applies the rubric using the scenario ground truth and the
    outcome, so the harness scores offline without a live model. A real judge is injected."""
    s, o = result.scenario, result.outcome
    score = RubricScore()

    # correct_handoff: escalation matches the scenario's need.
    handoff_ok = o.escalated == s.expect_escalated
    score.verdicts["correct_handoff"] = handoff_ok
    score.justifications["correct_handoff"] = (
        "escalation matches need" if handoff_ok else "escalation does not match need")

    # no_fabrication: a case that should escalate but was 'resolved' implies an invented answer.
    no_fab = not (s.expect_escalated and o.resolved and not o.escalated)
    score.verdicts["no_fabrication"] = no_fab
    score.justifications["no_fabrication"] = (
        "no unsupported claim" if no_fab else "resolved a case it could not legitimately resolve")

    # addressed_all_concerns: a resolvable case is only 'addressed' if it was resolved.
    addressed = o.resolved if s.expect_resolved else (o.escalated or not o.resolved)
    score.verdicts["addressed_all_concerns"] = addressed
    score.justifications["addressed_all_concerns"] = (
        "all concerns handled" if addressed else "left a concern unhandled")

    # accurate_facts: stand-in trusts the deterministic agent's citations.
    score.verdicts["accurate_facts"] = True
    score.justifications["accurate_facts"] = "no contradicting figures detected"
    return score


def judge_resolution(result: ScenarioResult, *, judge_fn: JudgeFn | None = None) -> RubricScore:
    """Score one conversation. With no ``judge_fn`` the deterministic stand-in runs; otherwise
    ``judge_fn`` receives the independent prompt (``build_judge_prompt``) and returns
    ``{key: (verdict, justification)}``."""
    if judge_fn is None:
        return _default_judge(result)
    raw = judge_fn(build_judge_prompt(result))
    score = RubricScore()
    for key, (verdict, reason) in raw.items():
        score.verdicts[key] = bool(verdict)
        score.justifications[key] = reason
    return score


def judge_suite(results: list[ScenarioResult], *, judge_fn: JudgeFn | None = None) -> dict:
    """Judge every conversation; return pass-rate + per-criterion pass-rates."""
    scores = [judge_resolution(r, judge_fn=judge_fn) for r in results]
    n = len(scores) or 1
    crit_rates = {c.key: sum(s.verdicts.get(c.key, False) for s in scores) / n for c in RUBRIC}
    return {
        "n": len(scores),
        "overall_pass_rate": sum(s.passed for s in scores) / n,
        "mean_score": sum(s.score for s in scores) / n,
        "by_criterion": crit_rates,
        "scores": scores,
    }
