"""Multi-pass independent review pipeline (SA-35).

Orchestrates the passes in ``passes.py`` into the review flow used at Definition-of-Done time:

1. a **per-file** pass for every changed file (local analysis), then
2. a single **cross-file integration** pass — but only when the change is big enough to
   warrant it (≥2 files and past a line threshold), so small diffs don't pay pass-splitting
   overhead.

The reviewer itself is **injected** (``review_fn``): in production it is a *second* ``anthropic``
client session — an independent instance with no access to the generator's reasoning — built by
``build_review_fn``. In tests a fake is injected so the orchestration is verified offline.

Findings carry self-reported confidence, so ``route`` splits them into auto-report
(high-confidence) vs human-triage (low-confidence) — calibrated review routing (cf. SA-20).
Exam: D4 TS 4.6.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .passes import (
    INTEGRATION,
    PER_FILE,
    Finding,
    dedupe,
    integration_prompt,
    parse_findings,
    per_file_prompt,
)

# A reviewer: given a prompt, return a list of raw finding dicts.
ReviewFn = Callable[[str], list[dict]]


@dataclass
class ReviewReport:
    findings: list[Finding] = field(default_factory=list)
    passes_run: list[str] = field(default_factory=list)

    def by_severity(self) -> list[Finding]:
        """Findings sorted most-severe first, then highest-confidence."""
        return sorted(self.findings, key=lambda f: (f.severity_rank, -f.confidence))

    @property
    def integration_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.pass_type == INTEGRATION]


def _changed_lines(diff: str) -> int:
    """Count added/removed lines in a unified diff (ignoring +++/--- file headers)."""
    n = 0
    for line in diff.splitlines():
        if (line.startswith("+") and not line.startswith("+++")) or \
           (line.startswith("-") and not line.startswith("---")):
            n += 1
    return n


def needs_integration_pass(files: dict[str, str], *, min_lines: int) -> bool:
    """A cross-file pass is only worth its cost when the change spans ≥2 files and is large
    enough — small diffs skip it to avoid pass-splitting overhead."""
    if len(files) < 2:
        return False
    return sum(_changed_lines(d) for d in files.values()) >= min_lines


def run_pipeline(files: dict[str, str], *, review_fn: ReviewFn,
                 min_lines_for_integration: int = 40) -> ReviewReport:
    """Run per-file passes over every changed file, then (for large multi-file changes) a single
    cross-file integration pass. Returns a de-duplicated report plus which passes ran."""
    findings: list[Finding] = []
    passes_run: list[str] = []

    for path, diff in files.items():
        raw = review_fn(per_file_prompt(path, diff))
        findings.extend(parse_findings(raw, PER_FILE, default_file=path))
        passes_run.append(f"per_file:{path}")

    if needs_integration_pass(files, min_lines=min_lines_for_integration):
        raw = review_fn(integration_prompt(files))
        findings.extend(parse_findings(raw, INTEGRATION))
        passes_run.append("integration")

    return ReviewReport(findings=dedupe(findings), passes_run=passes_run)


def route(findings: list[Finding], *, auto_threshold: float = 0.8) -> dict[str, list[Finding]]:
    """Calibrated routing: high-confidence findings are auto-reported; low-confidence ones go to
    human triage instead of being posted blindly (false positives destroy trust in auto-review,
    per review-criteria.md)."""
    auto = [f for f in findings if f.confidence >= auto_threshold]
    triage = [f for f in findings if f.confidence < auto_threshold]
    return {"auto_report": auto, "needs_triage": triage}


def _strip_code_fence(text: str) -> str:
    """Strip a Markdown code fence and an optional language tag from model output.

    Robust to a newline before the tag (```\\njson\\n[...]```): strip whitespace BEFORE the
    prefix check, then drop a leading ``json`` substring — not ``lstrip("json")``, which is a
    character-set strip that stops at the leading newline and leaves the tag in place (then
    json.loads fails and all findings are silently dropped)."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1].strip()   # removes leading newline before the tag
        text = text.removeprefix("json").strip()
    return text


def build_review_fn(model: str = "sonnet", *, client: Any | None = None) -> ReviewFn:
    """Build a production ``review_fn`` backed by a **second, independent** ``anthropic`` client
    session (lazy import — keeps this module import-safe without the SDK or a key). Each call is
    a single-shot Messages request that returns structured findings; the instance shares no
    state with whatever generated the code (D4 TS 4.6)."""
    def review_fn(prompt: str) -> list[dict]:
        import json

        nonlocal client
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        msg = client.messages.create(
            model=model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt + "\n\nReturn ONLY a JSON array of "
                       "findings (file, line, issue, severity, confidence, suggested_fix)."}],
        )
        text = _strip_code_fence("".join(getattr(b, "text", "") for b in msg.content))
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return []

    return review_fn
