"""Validation-retry loop (SA-18) — layer 3 of three.

Extract → semantically validate → on a *retryable* failure, re-extract with feedback
(original document + the failed extraction + the specific validation errors), up to a
max-retry cap, then dead-letter. A *non-retryable* failure (info absent from the source)
short-circuits immediately with a reason, so retries are never burned on unanswerable docs.

The model call is injected as ``extract_fn(document, attempt, feedback) -> model`` so the
whole loop — classification, retry, early-exit, dead-letter — is unit-testable offline.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from extraction.validate import ValidationReport
from extraction.validate import validate as default_validate

# status values
OK = "ok"                  # valid extraction
ABSENT_INFO = "absent_info"  # non-retryable: the source lacks the info — exited early
DEAD_LETTER = "dead_letter"  # retryable, but the cap was exhausted


@dataclass
class Outcome:
    status: str
    result: Any
    attempts: int
    report: ValidationReport | None = None
    reason: str = ""


def build_feedback(document: str, result: Any, report: ValidationReport) -> str:
    return (
        "Your previous extraction had these semantic errors — re-extract and fix ONLY these:\n"
        f"{report.to_feedback()}\n\n"
        f"Previous (failed) extraction:\n{result.model_dump_json()}\n\n"
        f"Original document:\n{document}"
    )


def run_extraction(
    document: str,
    *,
    extract_fn: Callable[[str, int, str | None], Any],
    validate_fn: Callable[[Any], ValidationReport] = default_validate,
    max_retries: int = 2,
) -> Outcome:
    """Run extraction with semantic validation and bounded retry-with-feedback."""
    result: Any = None
    report: ValidationReport | None = None
    feedback: str | None = None

    for attempt in range(max_retries + 1):
        result = extract_fn(document, attempt, feedback)
        report = validate_fn(result)
        if report.ok:
            return Outcome(OK, result, attempt + 1, report)
        if not report.retryable:
            # absent info — retrying won't help; exit early with the reason
            return Outcome(ABSENT_INFO, result, attempt + 1, report, reason=report.to_feedback())
        feedback = build_feedback(document, result, report)

    return Outcome(DEAD_LETTER, result, max_retries + 1, report,
                   reason="max retries exhausted; " + (report.to_feedback() if report else ""))
