"""Evaluation-harness tests (SA-30). Fully offline; fake agents injected.

Covers: the ≥30-scenario suite running end-to-end, every metric (FCR, both escalation
directions, tool routing, extraction-by-segment), the independent rubric judge, the JSON +
markdown report, and one full iteration (metric gap → criteria change → measured improvement).
"""
from __future__ import annotations

from eval.harness import AgentOutcome, compute_metrics, run_suite
from eval.judge import RUBRIC, build_judge_prompt, judge_resolution, judge_suite
from eval.report import metrics_to_dict, render_markdown, to_json
from eval.scenarios import CATEGORIES, load_scenarios


# --- a couple of fake agents ------------------------------------------------


def _oracle(scenario):
    """A near-perfect agent: does exactly what each scenario expects."""
    return AgentOutcome(
        resolved=scenario.expect_resolved,
        escalated=scenario.expect_escalated,
        tools_used=scenario.expected_tools,
        final_response="handled",
        extractions=tuple((dt, fld, True) for dt, fld in scenario.extraction_fields),
    )


def _under_escalating(scenario):
    """A flawed v1 agent: it never escalates policy-gap cases — it 'resolves' them instead
    (the failure mode the iteration fixes)."""
    if scenario.category == "policy_gap":
        return AgentOutcome(resolved=True, escalated=False,
                            tools_used=("get_customer",), final_response="approved")
    return _oracle(scenario)


# --- suite runs end-to-end across all categories ----------------------------


def test_suite_has_at_least_30_scenarios_across_five_categories():
    scenarios = load_scenarios()
    assert len(scenarios) >= 30
    assert {s.category for s in scenarios} == set(CATEGORIES)


def test_error_scenarios_carry_structured_injection_not_message_text():
    # The fault must live in inject_errors (tool, category), NOT as freeform text in the
    # message — otherwise the harness would feed the annotation to the agent as customer text.
    for s in load_scenarios("error_injection"):
        assert s.inject_errors, f"{s.id} has no structured injection"
        assert all("[" not in turn for turn in s.customer_turns), f"{s.id} leaks a text annotation"
        for tool, category in s.inject_errors:
            assert category in {"transient", "permission", "validation", "business"}


def test_agent_honoring_injection_escalates_on_real_tool_failure():
    # An agent that actually consults inject_errors and fails the named tool must escalate —
    # exercising the real "a tool raised" path, not "customer claims an error".
    def injecting_agent(scenario):
        failed_tools = {t for t, _ in scenario.inject_errors}
        if failed_tools:
            return AgentOutcome(resolved=False, escalated=True,
                                tools_used=tuple(scenario.expected_tools),
                                final_response="a backend tool failed; escalating")
        return _oracle(scenario)

    err = load_scenarios("error_injection")
    from eval.harness import run_scenario
    for s in err:
        result = run_scenario(s, injecting_agent)
        assert result.outcome.escalated and result.escalation_correct


def test_suite_runs_end_to_end_and_produces_metrics():
    results = run_suite(_oracle)
    metrics = compute_metrics(results)
    assert metrics.total == len(load_scenarios())
    # The oracle should hit everything.
    assert metrics.fcr_rate == 1.0
    assert metrics.correct_escalation_rate == 1.0
    assert metrics.tool_routing_accuracy == 1.0


# --- metrics: both escalation directions ------------------------------------


def test_escalation_confusion_matrix_counts_both_directions():
    results = run_suite(_under_escalating)
    m = compute_metrics(results)
    # Under-escalation: policy-gap cases that should escalate are missed (false negatives).
    assert m.escalation_fn == len(load_scenarios("policy_gap"))
    assert m.missed_escalation_rate > 0
    assert m.false_escalation_rate == 0.0      # it never over-escalates


def test_fcr_only_counts_resolvable_scenarios():
    # The oracle resolves all resolvable ones and escalates the rest → FCR 100%, not diluted
    # by the (correctly) unresolved escalation scenarios.
    m = compute_metrics(run_suite(_oracle))
    assert m.fcr_rate == 1.0


def test_extraction_accuracy_is_segmented_by_doc_type_and_field():
    def agent(scenario):
        out = _oracle(scenario)
        # Make one field wrong to prove segmentation surfaces it.
        if scenario.id == "std-8":
            return AgentOutcome(resolved=True, escalated=False, tools_used=out.tools_used,
                                extractions=(("damage_report", "damage_type", True),
                                             ("damage_report", "severity", False)))
        return out

    m = compute_metrics(run_suite(agent))
    assert m.extraction_accuracy[("damage_report", "severity")]["accuracy"] == 0.0
    assert ("damage_report", "severity") in m.worst_extraction_segments()


# --- independent judge ------------------------------------------------------


def test_judge_prompt_excludes_generation_context():
    results = run_suite(_oracle)
    prompt = build_judge_prompt(results[0])
    assert "INDEPENDENT" in prompt and "Rubric" in prompt
    assert "did not write this reply" in prompt
    # Explicit PASS/FAIL criteria, never a 1-10 scale.
    assert "PASS when" in prompt and "1-10" not in prompt


def test_judge_flags_fabricated_resolution_on_policy_gap():
    # An under-escalating agent 'resolves' a policy-gap case → judge fails handoff + fabrication.
    gap = load_scenarios("policy_gap")[0]
    from eval.harness import run_scenario
    result = run_scenario(gap, _under_escalating)
    score = judge_resolution(result)
    assert not score.passed
    assert score.verdicts["correct_handoff"] is False
    assert score.verdicts["no_fabrication"] is False


def test_judge_passes_correct_handling():
    results = run_suite(_oracle)
    summary = judge_suite(results)
    assert summary["overall_pass_rate"] == 1.0
    assert set(summary["by_criterion"]) == {c.key for c in RUBRIC}


def test_injected_judge_fn_is_used():
    results = run_suite(_oracle)
    captured = {}

    def fake_judge(prompt):
        captured["prompt"] = prompt
        return {c.key: (True, "looks fine") for c in RUBRIC}

    score = judge_resolution(results[0], judge_fn=fake_judge)
    assert score.passed and "Rubric" in captured["prompt"]


# --- report -----------------------------------------------------------------


def test_report_json_and_markdown():
    results = run_suite(_oracle)
    metrics = compute_metrics(results)
    summary = judge_suite(results)
    data = metrics_to_dict(metrics, summary)
    assert data["first_contact_resolution_rate"] == 1.0
    assert "escalation" in data and "tp" in data["escalation"]
    js = to_json(metrics, summary)
    assert "first_contact_resolution_rate" in js
    md = render_markdown(metrics, summary)
    assert "First-contact resolution" in md and "confusion matrix" in md
    assert "meets" in md  # oracle meets the 80% target


# --- the documented iteration: gap -> change -> improvement -----------------


def test_one_full_iteration_shows_measured_improvement():
    # v1: under-escalates policy-gap cases (the gap).
    before = compute_metrics(run_suite(_under_escalating))
    # v2: the fix — escalate policy gaps instead of fabricating a resolution (the oracle does).
    after = compute_metrics(run_suite(_oracle))

    # The gap is a missed-escalation problem; the change measurably improves it.
    assert before.missed_escalation_rate > 0.0
    assert after.missed_escalation_rate == 0.0
    assert after.correct_escalation_rate > before.correct_escalation_rate
    # And the independent judge agrees quality went up.
    before_judge = judge_suite(run_suite(_under_escalating))
    after_judge = judge_suite(run_suite(_oracle))
    assert after_judge["overall_pass_rate"] > before_judge["overall_pass_rate"]
