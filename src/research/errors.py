"""Structured subagent failure propagation + coverage annotation (SA-23).

Three subagent-failure anti-patterns this module rejects (exam D5 TS 5.3, sample Q8):

1. a **useless generic status** ("subagent failed") the coordinator can't act on;
2. a **fake empty success** that masks a timeout/auth failure as "no results found";
3. **killing the whole workflow** when one subagent fails.

Instead: a subagent **retries transient failures locally**; only an *unresolvable* error
propagates, and it propagates as a structured ``SubagentReport`` carrying the failure type,
the attempted query, any **partial results** gathered before failing, and **alternative
approaches**. The coordinator then *recovers* — retry a modified query, or proceed with
partial results — but **never terminates** on a single subagent failure. Finally, synthesis
**annotates coverage**: which topics are well-supported vs. which have gaps because a source
was unavailable — and a *valid empty result* (searched, found nothing) is kept distinct from
an *access failure*.

Mirrors the MCP error-envelope categories in ``mcp_server/errors.py`` (transient → retry;
permission/validation → not retryable as-is).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable

from research.schemas import Finding


class SubagentFailureType(str, Enum):
    TIMEOUT = "timeout"            # transient — a local retry may succeed
    RATE_LIMITED = "rate_limited"  # transient — a local retry may succeed
    ACCESS_DENIED = "access_denied"  # permission — not retryable as-is (source unavailable)
    INVALID_SCOPE = "invalid_scope"  # the scope was malformed — retry only with a modified query


# Only transient failures are worth a local retry (same mapping spirit as mcp_server/errors).
_RETRYABLE = {
    SubagentFailureType.TIMEOUT: True,
    SubagentFailureType.RATE_LIMITED: True,
    SubagentFailureType.ACCESS_DENIED: False,
    SubagentFailureType.INVALID_SCOPE: False,
}


class SubagentError(Exception):
    """Raised inside a subagent's work. Carries the failure type plus whatever was salvaged:
    partial findings collected before the failure, and alternative approaches to suggest
    upward. The retry wrapper decides whether to retry locally or propagate it."""

    def __init__(self, failure_type: SubagentFailureType, *, message: str = "",
                 partial: list[Finding] | None = None, alternatives: list[str] | None = None):
        super().__init__(message or failure_type.value)
        self.failure_type = failure_type
        self.partial = partial or []
        self.alternatives = alternatives or []


@dataclass
class SubagentReport:
    """A subagent's result — success or a structured, decision-enabling failure.

    The minimum viable structure for partial results is just ``findings`` (a possibly-empty,
    possibly-incomplete list of ``Finding``), so the coordinator can always use what was
    gathered. ``ok=True`` with empty ``findings`` is a **valid empty result** (searched, found
    nothing); ``ok=False`` is an **access failure** — the two are never conflated.
    """

    role: str
    scope: str
    findings: list[Finding] = field(default_factory=list)
    ok: bool = True
    failure_type: SubagentFailureType | None = None
    attempted_query: str | None = None
    alternative_approaches: list[str] = field(default_factory=list)
    attempts: int = 1

    @property
    def is_access_failure(self) -> bool:
        """A failure to reach/read the source — distinct from a valid empty result."""
        return not self.ok

    @property
    def is_valid_empty(self) -> bool:
        """A successful search that legitimately found nothing — NOT a failure."""
        return self.ok and not self.findings

    @property
    def is_retryable(self) -> bool:
        """Whether the *coordinator* could still retry this (transient that exhausted local
        attempts). Non-failures and permanent failures are not retryable."""
        return self.failure_type is not None and _RETRYABLE[self.failure_type]

    @classmethod
    def success(cls, role: str, scope: str, findings: list[Finding]) -> "SubagentReport":
        return cls(role=role, scope=scope, findings=list(findings), ok=True)

    @classmethod
    def failure(cls, role: str, scope: str, failure_type: SubagentFailureType, *,
                attempted_query: str, partial: list[Finding] | None = None,
                alternatives: list[str] | None = None, attempts: int = 1) -> "SubagentReport":
        return cls(role=role, scope=scope, findings=list(partial or []), ok=False,
                   failure_type=failure_type, attempted_query=attempted_query,
                   alternative_approaches=list(alternatives or []), attempts=attempts)


# A subagent's unit of work: (attempt_number) -> findings, or raise SubagentError.
ExecuteFn = Callable[[int], Awaitable[list[Finding]]]


async def run_subagent(role: str, scope: str, *, execute_fn: ExecuteFn,
                       attempted_query: str, max_attempts: int = 3) -> SubagentReport:
    """Run one subagent with **local** retry of transient failures.

    Retries TIMEOUT/RATE_LIMITED up to ``max_attempts``; a permanent failure (or an exhausted
    transient one) does not raise — it returns a structured failure report with the failure
    type, the attempted query, partial results, and alternatives. So an unresolvable error
    *propagates as data*, never as an exception that could kill the workflow.
    """
    last: SubagentError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            findings = await execute_fn(attempt)
            return SubagentReport.success(role, scope, findings)
        except SubagentError as exc:
            last = exc
            if _RETRYABLE[exc.failure_type] and attempt < max_attempts:
                continue  # transient — retry locally
            break         # permanent, or out of attempts → propagate
    assert last is not None  # loop only exits via return or after catching at least once
    return SubagentReport.failure(
        role, scope, last.failure_type, attempted_query=attempted_query,
        partial=last.partial, alternatives=last.alternatives,
        attempts=max_attempts if _RETRYABLE[last.failure_type] else 1,
    )


# --- coordinator recovery: never terminate on a single failure --------------

PROCEED = "proceed"                # use what we have (success, valid-empty, or partial results)
RETRY_MODIFIED = "retry_modified"  # re-delegate with a changed scope/approach


def plan_recovery(report: SubagentReport) -> str:
    """How the coordinator should react to one report. A bad scope, or any failure that came
    with suggested alternatives, warrants one *modified* retry; otherwise proceed with whatever
    partial results exist. Either way the workflow continues."""
    if report.ok:
        return PROCEED
    if report.failure_type is SubagentFailureType.INVALID_SCOPE or report.alternative_approaches:
        return RETRY_MODIFIED
    return PROCEED


RetryModifiedFn = Callable[[SubagentReport], Awaitable[SubagentReport]]


async def coordinate(tasks: list[tuple[str, str]], *, execute_fn: ExecuteFn,
                     retry_modified_fn: RetryModifiedFn | None = None,
                     max_attempts: int = 3) -> list[SubagentReport]:
    """Run every ``(role, scope)`` task, recovering from failures so the workflow NEVER
    terminates because one subagent failed.

    Each task is run with local retry; if it still fails and recovery says RETRY_MODIFIED (and
    a ``retry_modified_fn`` is supplied), one modified re-delegation is attempted. Whatever the
    outcome, a report is appended and the loop moves on — a single failure can never abort the
    run. The same ``execute_fn`` drives every task (tests inject faults per attempt).
    """
    reports: list[SubagentReport] = []
    for role, scope in tasks:
        report = await run_subagent(role, scope, execute_fn=execute_fn,
                                    attempted_query=scope, max_attempts=max_attempts)
        if not report.ok and plan_recovery(report) == RETRY_MODIFIED and retry_modified_fn:
            report = await retry_modified_fn(report)
        reports.append(report)
    return reports


# --- coverage annotation ----------------------------------------------------


@dataclass
class CoverageGap:
    scope: str
    reason: str            # the failure type that caused the gap
    attempted_query: str


@dataclass
class CoverageReport:
    """Which scopes are well-supported, which were searched-but-empty (valid), and which are
    gaps because a source was unavailable. Lets synthesis state its own coverage honestly."""

    supported: list[str] = field(default_factory=list)
    searched_empty: list[str] = field(default_factory=list)
    gaps: list[CoverageGap] = field(default_factory=list)

    @property
    def has_gaps(self) -> bool:
        return bool(self.gaps)


def assess_coverage(reports: list[SubagentReport]) -> CoverageReport:
    """Bucket reports into supported / valid-empty / gap. An access failure is a gap; a valid
    empty result is NOT — it is honestly reported as 'searched, nothing found'."""
    cov = CoverageReport()
    for r in reports:
        if r.is_access_failure:
            cov.gaps.append(CoverageGap(r.scope, (r.failure_type or "").value if r.failure_type
                                        else "unknown", r.attempted_query or r.scope))
        elif r.is_valid_empty:
            cov.searched_empty.append(r.scope)
        else:
            cov.supported.append(r.scope)
    return cov


def coverage_annotation(reports: list[SubagentReport]) -> str:
    """A human-readable coverage note for the final synthesis: well-supported topics vs. gaps
    due to unavailable sources (so a partial answer never masquerades as a complete one)."""
    cov = assess_coverage(reports)
    lines = ["## Coverage"]
    if cov.supported:
        lines.append(f"**Well-supported:** {', '.join(cov.supported)}")
    if cov.searched_empty:
        lines.append(f"**Searched, no results:** {', '.join(cov.searched_empty)}")
    if cov.gaps:
        lines.append("**Gaps (source unavailable):**")
        for g in cov.gaps:
            lines.append(f"  - {g.scope} — {g.reason} (attempted: {g.attempted_query})")
    else:
        lines.append("_No coverage gaps._")
    return "\n".join(lines)
