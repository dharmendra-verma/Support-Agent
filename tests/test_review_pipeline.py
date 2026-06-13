"""Multi-pass review-pipeline tests (SA-35). Fully offline; reviewer injected."""
from __future__ import annotations

from review.passes import (
    INTEGRATION,
    PER_FILE,
    Finding,
    dedupe,
    integration_prompt,
    parse_findings,
    per_file_prompt,
)
from review.pipeline import (
    ReviewReport,
    _strip_code_fence,
    needs_integration_pass,
    route,
    run_pipeline,
)


def _big(path, n=30):
    """A diff with ~n added lines (enough to clear the integration threshold when paired)."""
    return "\n".join(f"+    line_{i} = {i}" for i in range(n))


# --- prompts assert independence (no generator context) ---------------------


def test_prompts_frame_an_independent_reviewer():
    p = per_file_prompt("src/x.py", "+x = 1")
    assert "independent" in p.lower()
    # Explicitly excludes the author's reasoning/intent.
    assert "no access to the author" in p.lower() and "intent" in p.lower()


def test_integration_prompt_targets_cross_file_issues():
    ip = integration_prompt({"a.py": "+x=1", "b.py": "+y=2"})
    assert "integration" in ip.lower()
    assert "contract mismatch" in ip.lower() and "data-flow" in ip.lower()
    assert "### a.py" in ip and "### b.py" in ip   # all files present together


# --- pass orchestration + size threshold ------------------------------------


def test_small_single_file_diff_skips_integration_pass():
    report = run_pipeline({"a.py": "+x = 1"}, review_fn=lambda p: [])
    assert report.passes_run == ["per_file:a.py"]
    assert "integration" not in report.passes_run


def test_large_multifile_diff_runs_per_file_then_integration():
    files = {"a.py": _big("a.py"), "b.py": _big("b.py")}
    assert needs_integration_pass(files, min_lines=40)
    report = run_pipeline(files, review_fn=lambda p: [])
    assert report.passes_run == ["per_file:a.py", "per_file:b.py", "integration"]


def test_two_small_files_below_threshold_skip_integration():
    files = {"a.py": "+x = 1", "b.py": "+y = 2"}
    assert not needs_integration_pass(files, min_lines=40)
    report = run_pipeline(files, review_fn=lambda p: [])
    assert "integration" not in report.passes_run


# --- the integration pass finds a cross-file contract mismatch --------------


def test_integration_pass_finds_contract_mismatch_per_file_passes_miss():
    files = {"api.py": _big("api.py"), "caller.py": _big("caller.py")}

    def review_fn(prompt):
        # Per-file passes see each file alone and find nothing; only the cross-file pass,
        # seeing both, spots the signature/caller mismatch.
        if "integration pass" in prompt.lower():
            return [{"file": "caller.py", "line": 5,
                     "issue": "calls api.fetch() with the old 2-arg shape after it became 1-arg",
                     "severity": "high", "confidence": 0.85}]
        return []

    report = run_pipeline(files, review_fn=review_fn)
    assert report.integration_findings, "integration pass should surface the cross-file bug"
    f = report.integration_findings[0]
    assert f.pass_type == INTEGRATION and "shape" in f.issue


# --- independence: catches what self-review missed (same diff) ---------------


def test_independent_reviewer_catches_what_self_review_missed():
    # Same diff, two reviewers. "Self-review" (author-biased) rationalises the bug away and
    # returns nothing; the independent instance reports it.
    diff = {"src/x.py": "+def half(n):\n+    return n / 0   # oops"}

    def self_review(prompt):
        return []                       # misses its own bug

    def independent(prompt):
        return [{"file": "src/x.py", "line": 2, "issue": "division by zero",
                 "severity": "high", "confidence": 0.95, "suggested_fix": "divide by 2, not 0"}]

    missed = run_pipeline(diff, review_fn=self_review).findings
    caught = run_pipeline(diff, review_fn=independent).findings
    assert missed == []                                   # self-review found nothing
    assert any("division by zero" in f.issue for f in caught)   # independent caught it


# --- confidence-calibrated routing ------------------------------------------


def test_route_splits_high_and_low_confidence():
    findings = [
        Finding("a.py", 1, "definite bug", "high", confidence=0.9),
        Finding("b.py", 2, "maybe an issue", "low", confidence=0.4),
    ]
    r = route(findings, auto_threshold=0.8)
    assert [f.issue for f in r["auto_report"]] == ["definite bug"]
    assert [f.issue for f in r["needs_triage"]] == ["maybe an issue"]


def test_each_finding_carries_confidence():
    findings = parse_findings(
        [{"file": "a.py", "line": 3, "issue": "x", "severity": "medium", "confidence": 0.7}],
        PER_FILE)
    assert findings[0].confidence == 0.7


# --- aggregation: dedupe + severity ordering --------------------------------


def test_dedupe_keeps_highest_confidence_of_a_duplicate():
    a = Finding("a.py", 1, "same bug", "high", confidence=0.6)
    b = Finding("a.py", 1, "same bug", "high", confidence=0.9)
    out = dedupe([a, b])
    assert len(out) == 1 and out[0].confidence == 0.9


def test_report_orders_by_severity_then_confidence():
    report = ReviewReport(findings=[
        Finding("a.py", 1, "low thing", "low", confidence=0.9),
        Finding("b.py", 2, "critical thing", "critical", confidence=0.5),
        Finding("c.py", 3, "high thing (less sure)", "high", confidence=0.3),
        Finding("d.py", 4, "high thing (more sure)", "high", confidence=0.7),
    ])
    ordered = [f.issue for f in report.by_severity()]
    # Severity primary; within the SAME severity (both 'high'), higher confidence first.
    assert ordered == ["critical thing", "high thing (more sure)",
                       "high thing (less sure)", "low thing"]


def test_parse_tolerates_null_or_garbage_confidence():
    # LLM output may give confidence as null or a non-numeric string — must not crash.
    findings = parse_findings([
        {"file": "a.py", "issue": "x", "confidence": None},
        {"file": "b.py", "issue": "y", "confidence": "high"},
    ], PER_FILE)
    assert findings[0].confidence == 0.5 and findings[1].confidence == 0.5


def test_strip_code_fence_handles_tag_on_its_own_line():
    body = "[{\"file\": \"a.py\", \"issue\": \"x\"}]"
    # All these fence shapes must reduce to the same JSON — including a newline before "json".
    assert _strip_code_fence(f"```json\n{body}\n```") == body
    assert _strip_code_fence(f"```\njson\n{body}\n```") == body   # the lstrip bug case
    assert _strip_code_fence(f"```\n{body}\n```") == body
    assert _strip_code_fence(body) == body


def test_parse_fills_default_file_for_per_file_pass():
    # A per-file reviewer may omit the file (it was told which one) — orchestration fills it.
    findings = parse_findings([{"line": 1, "issue": "x"}], PER_FILE, default_file="src/y.py")
    assert findings[0].file == "src/y.py"
