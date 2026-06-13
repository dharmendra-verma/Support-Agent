"""Multi-agent research orchestration tests (SA-21). Fully offline — no SDK, no network.

Covers: coordinator/subagent specs, dynamic role selection, scope-partitioning
decomposition (and the reproduced too-narrow failure), the parallel-vs-sequential latency
model, and the iterative refinement loop driven by injected fakes.
"""
from __future__ import annotations

import asyncio

from research import agents
from research.coordinator import (
    Subtask,
    decompose,
    find_gaps,
    is_too_narrow,
    latency_seconds,
    naive_decompose,
    run_research,
    scopes_overlap,
    select_subagents,
)

# --- agent specs ------------------------------------------------------------


def test_coordinator_only_tool_is_task():
    # The coordinator plans and delegates — its sole tool is the subagent-spawner.
    assert agents.COORDINATOR.tools == ("Task",)


def test_each_subagent_is_role_scoped_and_small():
    # Selection reliability degrades with tool count (SA-13): keep every role's set tiny.
    for spec in agents.SUBAGENTS:
        assert len(spec.tools) <= 3
    # The synthesis role does no tool work — it merges.
    assert agents.subagent("synthesis").tools == ()


def test_unknown_subagent_fails_fast():
    try:
        agents.subagent("nope")
    except KeyError:
        return
    raise AssertionError("expected KeyError for unknown role")


# --- dynamic subagent selection ---------------------------------------------


def test_selection_is_dynamic_not_always_all():
    # A purely external question should not drag in doc/document subagents.
    roles = select_subagents("What is the latest news on our competitor's pricing?")
    assert "web_search" in roles
    assert "document_analysis" not in roles


def test_selection_adds_synthesis_when_multiple_researchers():
    roles = select_subagents("Compare our internal refund policy docs with the latest "
                             "industry news on refund windows")
    researchers = [r for r in roles if r != "synthesis"]
    assert len(researchers) >= 2
    assert "synthesis" in roles  # someone must own the merge


def test_selection_falls_back_to_web_search():
    roles = select_subagents("Tell me about quokkas")
    assert roles == ["web_search"]  # no signal matched → single attempt, no synthesis


# --- decomposition: non-overlapping scopes, goal-oriented prompts ------------


def test_decompose_partitions_into_non_overlapping_scopes():
    roles = select_subagents("Compare our internal policy docs against the latest online news")
    subtasks = decompose("Compare our internal policy docs against the latest online news", roles)
    assert not scopes_overlap(subtasks)             # partition, not duplication
    assert not is_too_narrow(subtasks)              # complementary roles, not slivers
    assert all(st.role != "synthesis" for st in subtasks)  # synthesis isn't a research slice


def test_subtask_prompts_are_self_contained_and_goal_oriented():
    subtasks = decompose("policy vs latest news", ["web_search", "doc_search", "synthesis"])
    for st in subtasks:
        # Self-contained: carries the full question (subagents inherit nothing).
        assert "policy vs latest news" in st.prompt
        # Goal-oriented, not procedural: states a goal + quality criteria.
        assert "GOAL" in st.prompt and "QUALITY CRITERIA" in st.prompt
        assert "Decide your own method" in st.prompt


def test_too_narrow_decomposition_is_reproduced_and_detected():
    bad = naive_decompose("How do refunds work?", n=5)
    assert is_too_narrow(bad)        # the failure mode is flagged
    assert all(st.role == "web_search" for st in bad)  # all slivers of one angle
    # Contrast: the proper decomposition of a multi-angle question is NOT too narrow.
    good = decompose("internal policy vs latest online news", ["doc_search", "web_search"])
    assert not is_too_narrow(good)


# --- latency: parallel fan-out vs sequential --------------------------------


def test_parallel_latency_is_slowest_task_not_the_sum():
    subtasks = [Subtask("web_search", "a", "p"), Subtask("doc_search", "b", "p"),
                Subtask("document_analysis", "c", "p")]
    par = latency_seconds(subtasks, mode="parallel", per_task=2.0)
    seq = latency_seconds(subtasks, mode="sequential", per_task=2.0)
    assert par == 2.0          # concurrent: one task's worth of wall-clock
    assert seq == 6.0          # serial: the sum
    assert par < seq           # parallel fan-out is the win


def test_empty_decomposition_has_zero_latency():
    assert latency_seconds([], mode="parallel") == 0.0


# --- iterative refinement loop ----------------------------------------------


def test_find_gaps_reports_unmet_criteria():
    assert find_gaps(["price", "availability"], "the price is $5") == ["availability"]


def test_refinement_loop_stops_early_when_criteria_met():
    calls = {"spawn": 0}

    async def spawn_fn(st):
        calls["spawn"] += 1
        return f"finding for {st.role}"

    async def synthesize_fn(findings):
        return "covers price and availability fully"  # satisfies criteria on round 1

    result = asyncio.run(run_research(
        "What is the latest price and availability?",
        spawn_fn=spawn_fn, synthesize_fn=synthesize_fn,
        criteria=["price", "availability"], max_rounds=3,
    ))
    assert result.rounds == 1          # stopped as soon as criteria were satisfied
    assert result.gaps == []


def test_refinement_loop_runs_another_round_to_close_a_gap():
    answers = iter([
        "covers price only",                       # round 1: availability still missing
        "covers price and availability now",       # round 2: gap closed
    ])

    async def spawn_fn(st):
        return f"finding for {st.scope}"

    async def synthesize_fn(findings):
        return next(answers)

    result = asyncio.run(run_research(
        "latest price and availability online",
        spawn_fn=spawn_fn, synthesize_fn=synthesize_fn,
        criteria=["price", "availability"], max_rounds=3,
    ))
    assert result.rounds == 2          # a second round was needed to close the gap
    assert result.gaps == []


def test_multiple_gaps_in_one_round_all_survive_to_synthesis():
    # Two criteria unmet after round 1 → two gap subtasks, both role="web_search".
    # Findings must be keyed so neither overwrites the other before synthesis sees them.
    seen_findings: list[dict] = []

    async def spawn_fn(st):
        return f"finding for [{st.scope}]"

    async def synthesize_fn(findings):
        seen_findings.append(dict(findings))
        return "round-1 covers nothing"   # both criteria stay unmet → one refine round

    asyncio.run(run_research(
        "broad question", spawn_fn=spawn_fn, synthesize_fn=synthesize_fn,
        criteria=["alpha", "beta"], max_rounds=2,
    ))
    # On the refinement round both gap findings must be present (distinct keys), not one.
    last = seen_findings[-1]
    assert sum("alpha" in v for v in last.values()) == 1
    assert sum("beta" in v for v in last.values()) == 1


def test_refinement_loop_is_bounded_by_max_rounds():
    async def spawn_fn(st):
        return "nothing useful"

    async def synthesize_fn(findings):
        return "still incomplete"      # never satisfies the criterion

    result = asyncio.run(run_research(
        "impossible question",
        spawn_fn=spawn_fn, synthesize_fn=synthesize_fn,
        criteria=["unobtainium"], max_rounds=2,
    ))
    assert result.rounds == 2          # capped — the safety net, not the primary stop
    assert result.gaps == ["unobtainium"]
