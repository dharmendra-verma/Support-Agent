"""Review passes + structured findings for the multi-pass reviewer (SA-35).

Two pass types, mirroring how a careful human reviews a large change:

* **per-file** — local analysis of one file's diff in isolation (logic bugs, missing guards,
  inverted conditions). Cheap and parallelisable.
* **integration** — a single cross-file pass over ALL changed files together, hunting the
  bugs no single-file pass can see: data-flow breaks, **contract mismatches** between a
  changed callee and its callers, ordering/timing dependencies.

Both passes are framed for an **independent reviewer** that has *no access to the author's
reasoning* — the prompt carries only the diff, never any generation rationale. That
independence is exactly why a second instance catches what self-review rationalises away
(exam D4 TS 4.6).

Each finding self-reports a **confidence** so downstream routing can be calibrated (auto-post
high-confidence, send low-confidence to human triage) — the SA-20 routing idea applied to
review.
"""
from __future__ import annotations

from dataclasses import dataclass

PER_FILE = "per_file"
INTEGRATION = "integration"

_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


@dataclass
class Finding:
    """One structured review finding (location, issue, severity, confidence, fix)."""

    file: str
    line: int | None
    issue: str
    severity: str = "medium"
    confidence: float = 0.5          # reviewer's self-reported 0.0–1.0 confidence
    suggested_fix: str = ""
    pass_type: str = PER_FILE
    detected_pattern: str = ""       # stable key for dismissal tracking (review-criteria.md)

    @property
    def severity_rank(self) -> int:
        return _SEVERITY_RANK.get(self.severity, 99)

    def key(self) -> tuple:
        """Identity for de-duplication: same file+line+issue is the same finding."""
        return (self.file, self.line, self.issue.strip().lower())


_INDEPENDENCE_PREAMBLE = (
    "You are an INDEPENDENT code reviewer. You did NOT write this change and you have NO "
    "access to the author's reasoning or intent — review only the diff shown. Judge what the "
    "code actually does, not what it was meant to do. For each finding report: file, line, "
    "issue, severity (critical/high/medium/low), a confidence 0.0–1.0, and a suggested fix."
)


def per_file_prompt(path: str, diff: str) -> str:
    """Prompt for a local, single-file analysis pass."""
    return (
        f"{_INDEPENDENCE_PREAMBLE}\n\n"
        f"## Per-file pass — analyse ONLY `{path}` in isolation\n"
        "Look for local defects: inverted/wrong conditions, off-by-one, null/None deref, "
        "missing await, swallowed errors, falsy-zero checks, copy-paste slips.\n\n"
        f"### Diff for {path}\n{diff}"
    )


def integration_prompt(files: dict[str, str]) -> str:
    """Prompt for the cross-file integration pass over all changed files together."""
    blocks = "\n\n".join(f"### {path}\n{diff}" for path, diff in files.items())
    return (
        f"{_INDEPENDENCE_PREAMBLE}\n\n"
        "## Integration pass — cross-file analysis of ALL changed files TOGETHER\n"
        "Hunt only the issues a single-file pass CANNOT see: data-flow breaks between files, "
        "CONTRACT MISMATCHES (a changed function's signature/return shape vs its callers), "
        "ordering/timing dependencies, and duplicated or contradictory logic across files.\n\n"
        f"{blocks}"
    )


def parse_findings(raw: list[dict], pass_type: str, *, default_file: str | None = None) -> list[Finding]:
    """Convert a reviewer's raw finding dicts into ``Finding`` objects, tagging the pass type.
    Missing fields fall back to safe defaults; ``default_file`` fills in the file for a per-file
    pass where the reviewer omitted it (it was told which file it's reviewing)."""
    findings: list[Finding] = []
    for r in raw or []:
        # Guard the cast: an LLM may emit confidence as null or a non-numeric string. r.get's
        # default only fires for an ABSENT key, so null/garbage would otherwise crash float().
        raw_conf = r.get("confidence")
        confidence = float(raw_conf) if isinstance(raw_conf, (int, float)) else 0.5
        findings.append(Finding(
            file=r.get("file") or default_file or "?",
            line=r.get("line"),
            issue=r.get("issue", ""),
            severity=str(r.get("severity", "medium")).lower(),
            confidence=confidence,
            suggested_fix=r.get("suggested_fix", ""),
            pass_type=pass_type,
            detected_pattern=r.get("detected_pattern", ""),
        ))
    return findings


def dedupe(findings: list[Finding]) -> list[Finding]:
    """Collapse duplicate findings (same file+line+issue), keeping the highest-confidence one.
    Order is preserved by first appearance."""
    best: dict[tuple, Finding] = {}
    order: list[tuple] = []
    for f in findings:
        k = f.key()
        if k not in best:
            best[k] = f
            order.append(k)
        elif f.confidence > best[k].confidence:
            best[k] = f
    return [best[k] for k in order]
