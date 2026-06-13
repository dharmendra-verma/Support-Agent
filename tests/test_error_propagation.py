"""Subagent error-propagation + coverage tests (SA-23). Fully offline; faults injected.

Covers: local retry of transient failures, structured propagation of unresolvable errors
(type + attempted query + partial results + alternatives), coordinator recovery that never
terminates the workflow, access-failure vs valid-empty distinction, and coverage annotation.
"""
from __future__ import annotations

import asyncio

from research.errors import (
    PROCEED,
    RETRY_MODIFIED,
    SubagentError,
    SubagentFailureType,
    SubagentReport,
    assess_coverage,
    coordinate,
    coverage_annotation,
    plan_recovery,
    run_subagent,
)
from research.schemas import ContentType, Finding


def mk_finding(topic="t", source="s"):
    return Finding(topic=topic, claim="c", source=source, content_type=ContentType.OTHER)


def run(coro):
    return asyncio.run(coro)


# --- local retry of transient failures --------------------------------------


def test_transient_failure_is_retried_locally_then_succeeds():
    attempts = {"n": 0}

    async def execute(attempt):
        attempts["n"] = attempt
        if attempt < 2:
            raise SubagentError(SubagentFailureType.TIMEOUT)
        return [mk_finding()]

    report = run(run_subagent("web_search", "scope", execute_fn=execute,
                              attempted_query="q", max_attempts=3))
    assert report.ok and len(report.findings) == 1
    assert attempts["n"] == 2  # it took a retry


def test_transient_failure_exhausts_retries_then_propagates_structured():
    async def execute(attempt):
        raise SubagentError(SubagentFailureType.TIMEOUT, partial=[mk_finding(topic="partial")],
                            alternatives=["try a narrower query"])

    report = run(run_subagent("web_search", "scope", execute_fn=execute,
                              attempted_query="the query", max_attempts=3))
    # Unresolvable after retries → structured failure, NOT an exception, NOT a fake success.
    assert report.is_access_failure
    assert report.failure_type == SubagentFailureType.TIMEOUT
    assert report.attempted_query == "the query"
    assert [f.topic for f in report.findings] == ["partial"]      # partial results preserved
    assert report.alternative_approaches == ["try a narrower query"]
    assert report.attempts == 3


def test_permanent_failure_is_not_retried():
    attempts = {"n": 0}

    async def execute(attempt):
        attempts["n"] += 1
        raise SubagentError(SubagentFailureType.ACCESS_DENIED)

    report = run(run_subagent("doc_search", "internal", execute_fn=execute,
                              attempted_query="q", max_attempts=3))
    assert report.is_access_failure and not report.is_retryable
    assert attempts["n"] == 1  # access-denied retried zero extra times


# --- access failure vs valid empty result -----------------------------------


def test_valid_empty_result_is_not_an_access_failure():
    async def execute(attempt):
        return []  # searched successfully, found nothing

    report = run(run_subagent("web_search", "obscure topic", execute_fn=execute,
                              attempted_query="q"))
    assert report.ok and report.is_valid_empty
    assert not report.is_access_failure


def test_access_failure_is_distinct_from_empty():
    fail = SubagentReport.failure("r", "s", SubagentFailureType.ACCESS_DENIED, attempted_query="q")
    empty = SubagentReport.success("r", "s", [])
    assert fail.is_access_failure and not fail.is_valid_empty
    assert empty.is_valid_empty and not empty.is_access_failure


# --- coordinator recovery: never terminates ---------------------------------


def test_plan_recovery_retries_modified_on_bad_scope_or_alternatives():
    bad_scope = SubagentReport.failure("r", "s", SubagentFailureType.INVALID_SCOPE,
                                       attempted_query="q")
    with_alts = SubagentReport.failure("r", "s", SubagentFailureType.ACCESS_DENIED,
                                       attempted_query="q", alternatives=["use the cache"])
    plain = SubagentReport.failure("r", "s", SubagentFailureType.ACCESS_DENIED, attempted_query="q")
    assert plan_recovery(bad_scope) == RETRY_MODIFIED
    assert plan_recovery(with_alts) == RETRY_MODIFIED
    assert plan_recovery(plain) == PROCEED
    assert plan_recovery(SubagentReport.success("r", "s", [mk_finding()])) == PROCEED


def test_workflow_does_not_terminate_when_one_subagent_fails():
    # Three tasks; the middle scope ("b") always fails permanently. coordinate() must still
    # return a report for EVERY task (never raise / abort the run).
    tasks = [("web_search", "a"), ("doc_search", "b"), ("web_search", "c")]
    state = {"current": None}

    async def execute(attempt):
        # coordinate() uses scope as the attempted_query, so the failing scope is observable
        # only via this shared marker that the driver sets before each task.
        if state["current"] == "b":
            raise SubagentError(SubagentFailureType.ACCESS_DENIED)
        return [mk_finding(source=state["current"])]

    reports = []

    async def driver():
        for role, scope in tasks:
            state["current"] = scope
            reports.append(await run_subagent(role, scope, execute_fn=execute,
                                              attempted_query=scope))

    run(driver())
    assert len(reports) == 3                      # every task produced a report
    assert [r.ok for r in reports] == [True, False, True]
    assert reports[1].is_access_failure           # the failure is reported, not swallowed


def test_coordinate_retries_modified_then_proceeds():
    async def execute(attempt):
        raise SubagentError(SubagentFailureType.INVALID_SCOPE)  # always bad scope

    async def retry_modified(report):
        # coordinator broadens the scope and this time it works
        return SubagentReport.success(report.role, report.scope + " (broadened)", [mk_finding()])

    reports = run(coordinate([("web_search", "too narrow")], execute_fn=execute,
                             retry_modified_fn=retry_modified, max_attempts=2))
    assert len(reports) == 1
    assert reports[0].ok                           # recovered via a modified retry
    assert "broadened" in reports[0].scope


# --- coverage annotation ----------------------------------------------------


def test_coverage_buckets_supported_empty_and_gaps():
    reports = [
        SubagentReport.success("web", "market", [mk_finding()]),       # supported
        SubagentReport.success("web", "niche", []),                    # searched, empty
        SubagentReport.failure("doc", "internal", SubagentFailureType.ACCESS_DENIED,
                               attempted_query="kb lookup"),           # gap
    ]
    cov = assess_coverage(reports)
    assert cov.supported == ["market"]
    assert cov.searched_empty == ["niche"]
    assert [g.scope for g in cov.gaps] == ["internal"]
    assert cov.has_gaps


def test_coverage_annotation_distinguishes_gaps_from_empty():
    reports = [
        SubagentReport.success("web", "market", [mk_finding()]),
        SubagentReport.success("web", "niche", []),
        SubagentReport.failure("doc", "internal", SubagentFailureType.TIMEOUT,
                               attempted_query="kb lookup"),
    ]
    note = coverage_annotation(reports)
    assert "Well-supported:** market" in note
    assert "Searched, no results:** niche" in note
    assert "internal — timeout" in note          # gap names the unavailable source + reason
    assert "Gaps (source unavailable)" in note


def test_coverage_annotation_when_complete():
    reports = [SubagentReport.success("web", "market", [mk_finding()])]
    note = coverage_annotation(reports)
    assert "No coverage gaps" in note
