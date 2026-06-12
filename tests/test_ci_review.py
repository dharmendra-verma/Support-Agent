"""Offline tests for the CI review tooling (no `claude`/`gh`/network).

Covers the report-vs-skip filter, re-run dedup, comment round-tripping, the
non-interactive command vector, and the per-file + integration orchestration.
"""
from __future__ import annotations

from ci import post_comments as pc
from ci import run_review as rr


def finding(**kw):
    base = {
        "file": "src/agent/loop.py",
        "line": 42,
        "category": "bug",
        "severity": "high",
        "issue": "inverted condition",
        "suggested_fix": "flip it",
        "detected_pattern": "inverted-cond",
    }
    base.update(kw)
    return base


# --- report-vs-skip ---------------------------------------------------------


def test_filter_keeps_bug_and_security():
    findings = [finding(category="bug"), finding(category="security", detected_pattern="sec")]
    assert len(pc.filter_reportable(findings)) == 2


def test_filter_drops_style_nit_subjective():
    findings = [finding(category="style"), finding(category="nit"), finding(category="subjective")]
    assert pc.filter_reportable(findings) == []


def test_filter_drops_low_severity():
    assert pc.filter_reportable([finding(severity="low")]) == []


def test_filter_drops_dismissed_pattern():
    findings = [finding(detected_pattern="known-noise")]
    assert pc.filter_reportable(findings, dismissed_patterns={"known-noise"}) == []


# --- dedup / re-runs --------------------------------------------------------


def test_select_new_skips_already_posted():
    f = finding()
    posted = {pc.finding_key(f)}
    assert pc.select_new([f], posted) == []


def test_select_new_dedups_within_batch():
    f = finding()
    assert len(pc.select_new([f, dict(f)], set())) == 1


def test_comment_key_roundtrip():
    """A posted comment's embedded key is recoverable, so re-runs won't repost it."""
    f = finding()
    body = pc.format_comment(f)
    assert pc.extract_posted_keys([body]) == {pc.finding_key(f)}


def test_reportable_new_pipeline():
    bug, style = finding(), finding(category="style", detected_pattern="s")
    posted = {pc.finding_key(finding(detected_pattern="old", file="x.py", line=1))}
    out = pc.reportable_new([bug, style], posted)
    assert out == [bug]  # style skipped, bug kept (not previously posted)


def test_load_findings_accepts_both_shapes():
    assert pc.load_findings('{"findings": [{"a": 1}]}') == [{"a": 1}]
    assert pc.load_findings("[{\"a\": 1}]") == [{"a": 1}]
    assert pc.load_findings("") == []


# --- run_review -------------------------------------------------------------


def test_build_command_is_noninteractive_and_headless():
    cmd = rr.build_command("review please")
    assert cmd[:2] == ["claude", "-p"]
    assert "--output-format" in cmd and "json" in cmd
    # bypassPermissions stops CI hangs on tool-approval prompts; max-turns 1 keeps
    # the call to a single direct answer from the diff (no slow tool exploration)
    assert "--permission-mode" in cmd and "bypassPermissions" in cmd
    assert "--max-turns" in cmd
    # --json-schema hangs this CLI; the JSON shape is specified in the prompt instead
    assert "--json-schema" not in cmd


def test_parse_review_output_extracts_findings_from_envelope():
    env = '{"type":"result","result":"{\\"findings\\": [{\\"file\\": \\"a.py\\"}]}"}'
    assert rr.parse_review_output(env) == {"findings": [{"file": "a.py"}]}


def test_parse_review_output_strips_markdown_fences():
    env = '{"result":"```json\\n{\\"findings\\": []}\\n```"}'
    assert rr.parse_review_output(env) == {"findings": []}


def test_parse_review_output_wraps_bare_list_and_handles_empty():
    assert rr.parse_review_output('{"result":"[{\\"file\\":\\"x\\"}]"}') == {"findings": [{"file": "x"}]}
    assert rr.parse_review_output('{"result":""}') == {"findings": []}


def test_file_prompt_embeds_diff_and_criteria():
    p = rr.build_file_prompt("src/agent/loop.py", "@@ -1 +1 @@\n-old\n+new")
    assert "src/agent/loop.py" in p
    assert "review-criteria.md" in p
    assert "detected_pattern" in p
    assert "+new" in p  # diff embedded → reviewer needs no tools
    assert "do not use any tools" in p.lower()


def test_integration_prompt_is_cross_file_with_diff():
    p = rr.build_integration_prompt(["a.py", "b.py"], "DIFFBODY")
    assert "a.py" in p and "b.py" in p
    assert "interact" in p.lower() or "span" in p.lower()
    assert "DIFFBODY" in p


def test_testgen_prompt_avoids_duplication():
    p = rr.build_testgen_prompt("src/agent/loop.py", ["tests/test_loop.py"])
    assert "tests/test_loop.py" in p
    assert "not duplicate" in p.lower()
    assert "offline" in p.lower()


def test_collect_findings_runs_per_file_plus_integration(monkeypatch):
    monkeypatch.setattr(rr, "changed_files", lambda base, head: ["a.py", "b.py"])
    monkeypatch.setattr(rr, "file_diff", lambda base, head, path: f"diff {path}")
    monkeypatch.setattr(rr, "full_diff", lambda base, head, paths: "full diff")
    calls = []

    def fake_runner(prompt):
        calls.append(prompt)
        return {"findings": [finding()]}

    out = rr.collect_findings("main", "HEAD", runner=fake_runner)
    assert len(calls) == 3  # 2 files + 1 integration pass
    assert len(out["findings"]) == 3
