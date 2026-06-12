"""Filter CI review findings and post them as PR comments.

The reviewer (`claude -p`, see run_review.py) emits findings matching
`ci/review_schema.json`. This script decides which to surface (report-vs-skip per
`.claude/standards/review-criteria.md`), drops anything already posted on the PR
(so re-runs only show new/unaddressed issues), and posts the rest.

Design: the decision logic is pure and unit-tested (tests/test_ci_review.py). The
GitHub I/O (reading prior comments, posting) lives in the thin `main()` / `gh_*`
shell and shells out to `gh`; it is not exercised by the offline test suite.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

# Mirrors .claude/standards/review-criteria.md — keep in sync.
REPORT_CATEGORIES = frozenset({"bug", "security", "correctness-test", "breaking-change"})
SKIP_SEVERITIES = frozenset({"low"})

MARKER = "resolvedesk-ci-review"
_KEY_RE = re.compile(r"<!--\s*" + MARKER + r" key=(?P<key>[^\s]+)\s*-->")


def load_findings(raw: str) -> list[dict]:
    """Parse reviewer output: either {"findings": [...]} or a bare [...]."""
    data = json.loads(raw) if raw.strip() else {}
    if isinstance(data, dict):
        data = data.get("findings", [])
    return list(data)


def finding_key(f: dict) -> str:
    """Stable identity for dedup: pattern + location."""
    return f"{f['detected_pattern']}::{f['file']}::{f['line']}"


def filter_reportable(findings: list[dict], dismissed_patterns=frozenset()) -> list[dict]:
    """Keep only report-worthy findings: an allowed category, not a skipped severity,
    and not a dismissed detected_pattern."""
    kept = []
    for f in findings:
        if f.get("category") not in REPORT_CATEGORIES:
            continue
        if f.get("severity") in SKIP_SEVERITIES:
            continue
        if f.get("detected_pattern") in dismissed_patterns:
            continue
        kept.append(f)
    return kept


def extract_posted_keys(comment_bodies) -> set[str]:
    """Recover finding keys we previously embedded in our own PR comments."""
    keys: set[str] = set()
    for body in comment_bodies:
        keys.update(_KEY_RE.findall(body or ""))
    return keys


def select_new(findings: list[dict], posted_keys: set[str]) -> list[dict]:
    """Drop findings already posted (by key); dedup within this batch too."""
    seen = set(posted_keys)
    fresh = []
    for f in findings:
        key = finding_key(f)
        if key in seen:
            continue
        seen.add(key)
        fresh.append(f)
    return fresh


def format_comment(f: dict) -> str:
    """Render a finding as a PR comment, embedding its key for future dedup."""
    key = finding_key(f)
    return (
        f"<!-- {MARKER} key={key} -->\n"
        f"**[{f['severity']} · {f['category']}] {f['issue']}**\n\n"
        f"**Suggested fix:** {f['suggested_fix']}\n\n"
        f"<sub>pattern: `{f['detected_pattern']}`</sub>"
    )


def reportable_new(findings, posted_keys, dismissed_patterns=frozenset()):
    """Full pipeline: report-vs-skip → drop already-posted/dupes. Pure; tested."""
    return select_new(filter_reportable(findings, dismissed_patterns), posted_keys)


# --- thin GitHub I/O shell (not unit-tested; needs a live PR + gh auth) ----------


def gh_prior_comment_bodies(repo: str, pr: str) -> list[str]:
    out = subprocess.run(
        ["gh", "api", f"repos/{repo}/issues/{pr}/comments", "--paginate", "--jq", ".[].body"],
        capture_output=True, text=True, check=True,
    ).stdout
    return [line for line in out.splitlines() if line]


def gh_post_comment(repo: str, pr: str, body: str) -> None:
    subprocess.run(
        ["gh", "api", f"repos/{repo}/issues/{pr}/comments", "--method", "POST", "-f", f"body={body}"],
        check=True,
    )


def main(argv: list[str]) -> int:
    # usage: post_comments.py <findings.json> <repo> <pr> [dismissed.json]
    findings_path, repo, pr = argv[1], argv[2], argv[3]
    dismissed = frozenset()
    if len(argv) > 4 and Path(argv[4]).exists():
        dismissed = frozenset(json.loads(Path(argv[4]).read_text()))

    findings = load_findings(Path(findings_path).read_text())
    posted = extract_posted_keys(gh_prior_comment_bodies(repo, pr))
    to_post = reportable_new(findings, posted, dismissed)

    for f in to_post:
        gh_post_comment(repo, pr, format_comment(f))
    print(f"posted {len(to_post)} new finding(s); {len(posted)} already on PR")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
