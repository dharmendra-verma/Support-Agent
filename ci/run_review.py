"""Run the non-interactive Claude reviewer over a PR's changes.

Reviews each changed file on its own, then runs ONE integration pass over the whole
diff (cross-file issues a per-file view misses). Emits a single merged findings JSON
matching ci/review_schema.json for post_comments.py to filter and post.

The CLI invocation is isolated in `run_claude()`; prompt assembly and the command
vector (`build_command`) are pure and unit-tested. `claude -p` is non-interactive, so
the CI job never hangs waiting for input.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("review_schema.json")
CRITERIA_REF = ".claude/standards/review-criteria.md"

# Reviewer model — Sonnet by default (fast/cheaper than Opus, ample for diff review).
# Override per-environment with REVIEW_MODEL (e.g. "opus", "haiku", or a full model id).
REVIEW_MODEL = os.environ.get("REVIEW_MODEL", "sonnet")

# Review Python source and YAML config (workflows/actions) — both can carry real
# correctness/breaking-change bugs. Docs/markdown/json are still excluded as review noise.
CODE_SUFFIXES = (".py", ".yml", ".yaml")

# Per-file + integration passes run concurrently so wall-time ≈ slowest single
# call, not the sum — without this the sequential calls overran the CI timeout.
MAX_WORKERS = 4


def changed_files(base: str, head: str) -> list[str]:
    """Code files changed between base and head (added/modified, not deleted)."""
    out = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=d", f"{base}...{head}"],
        capture_output=True, text=True, check=True,
    ).stdout
    return [p for p in out.splitlines() if p.endswith(CODE_SUFFIXES)]


def file_diff(base: str, head: str, path: str) -> str:
    """Unified diff for one file — embedded in the prompt so the reviewer needs no tools."""
    return subprocess.run(
        ["git", "diff", f"{base}...{head}", "--", path],
        capture_output=True, text=True, check=True,
    ).stdout


def full_diff(base: str, head: str, paths: list[str]) -> str:
    """Combined diff for the integration pass.

    Returns "" for an empty path list — otherwise `git diff base...head --` has no
    pathspec and git diffs the WHOLE repo (caught by the CI reviewer itself)."""
    if not paths:
        return ""
    return subprocess.run(
        ["git", "diff", f"{base}...{head}", "--", *paths],
        capture_output=True, text=True, check=True,
    ).stdout


def _criteria_clause() -> str:
    return (
        f"Apply the review criteria in {CRITERIA_REF}: REPORT only bug, security, "
        "correctness-test, and breaking-change findings; SKIP style/nit/subjective "
        "(ruff and humans own those). Default to NOT reporting when unsure — a false "
        "positive is worse than a miss. Each finding needs a stable detected_pattern key. "
        'Return ONLY a JSON object, no prose and no markdown fences, of the form: '
        '{"findings": [{"file": str, "line": int, "category": str, "severity": str, '
        '"issue": str, "suggested_fix": str, "detected_pattern": str}]}. '
        "Use an empty findings array if there are no issues."
    )


_NO_TOOLS = (
    "Analyze ONLY the unified diff below — do not use any tools (no Read/Bash/etc.); "
    "everything you need is in the diff."
)


def build_file_prompt(path: str, diff: str) -> str:
    return (
        f"Review the changes to `{path}` for correctness defects only. {_NO_TOOLS}\n\n"
        f"{_criteria_clause()}\n\n```diff\n{diff}\n```"
    )


def build_integration_prompt(paths: list[str], diff: str) -> str:
    listed = ", ".join(f"`{p}`" for p in paths) or "(none)"
    return (
        "Integration pass: from the combined diff below, review how the changed files "
        "interact — broken call sites, changed return shapes, ordering/timing "
        f"dependencies, and contracts that span files. Changed files: {listed}. "
        f"{_NO_TOOLS}\n\n{_criteria_clause()}\n\n```diff\n{diff}\n```"
    )


def build_testgen_prompt(path: str, existing_test_files: list[str]) -> str:
    """Prompt for generating tests that DON'T duplicate existing coverage."""
    listed = ", ".join(f"`{t}`" for t in existing_test_files) or "(none yet)"
    return (
        f"Generate pytest tests for `{path}`. First READ the existing tests ({listed}) "
        "and do NOT duplicate scenarios already covered — add tests only for uncovered "
        "behavior and edge cases. Tests must run offline (no network, no API key) and "
        "follow .claude/rules/testing.md. Output only the new test code."
    )


# Seconds a single review call may run before we give up on it (and skip that pass)
# rather than letting one stuck call hang the whole CI job.
CALL_TIMEOUT_S = 120


def build_command(prompt: str) -> list[str]:
    """The non-interactive reviewer invocation.

    `-p` = print mode (no REPL). `--permission-mode bypassPermissions` keeps tool use
    from blocking on an approval prompt; `--max-turns 1` forces a direct answer from the
    diff in the prompt. We deliberately do NOT pass `--json-schema` — on this CLI it hangs
    the call; the JSON shape is specified in the prompt instead.
    """
    return [
        "claude", "-p", prompt,
        "--model", REVIEW_MODEL,
        "--output-format", "json",
        "--permission-mode", "bypassPermissions",
        "--max-turns", "1",
    ]


def parse_review_output(stdout: str) -> dict:
    """`--output-format json` wraps the model's answer in a result envelope; the findings
    JSON we want is the string in `.result`. Extract it, strip any markdown fences, parse."""
    envelope = json.loads(stdout)
    text = envelope.get("result", "") if isinstance(envelope, dict) else ""
    text = (text or "").strip()
    if text.startswith("```"):
        # drop the opening ```lang line and the closing ``` fence
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0].strip()
    if not text:
        return {"findings": []}
    data = json.loads(text)
    return {"findings": data} if isinstance(data, list) else data


def run_claude(prompt: str) -> dict:
    """Invoke the reviewer and parse its findings. Isolated so tests don't spawn the CLI.

    A stuck call is bounded by CALL_TIMEOUT_S and treated as 'no findings' so it can't
    sink the whole job."""
    try:
        proc = subprocess.run(
            build_command(prompt),
            capture_output=True, text=True, timeout=CALL_TIMEOUT_S,
            stdin=subprocess.DEVNULL,  # CI has no TTY — never block waiting on stdin/prompts
        )
    except subprocess.TimeoutExpired as exc:
        tail = ((exc.stderr or exc.stdout or "") if isinstance(exc.stderr or exc.stdout, str) else "")[-600:]
        print(
            f"warning: review call timed out after {CALL_TIMEOUT_S}s; skipping. "
            f"partial output: {tail!r}",
            file=sys.stderr,
        )
        return {"findings": []}
    if proc.returncode != 0:
        raise RuntimeError(f"claude review failed ({proc.returncode}): {proc.stderr.strip()}")
    return parse_review_output(proc.stdout)


def merge_findings(results: list[dict]) -> dict:
    """Flatten per-pass {"findings": [...]} payloads into one."""
    merged: list[dict] = []
    for r in results:
        merged.extend(r.get("findings", []))
    return {"findings": merged}


def collect_findings(base: str, head: str, runner=run_claude, max_workers: int = MAX_WORKERS) -> dict:
    """Per-file passes + one integration pass → merged findings.

    Passes run concurrently (order preserved) so the CI job stays well under its
    timeout. `runner` is injectable for offline tests.
    """
    files = changed_files(base, head)
    if not files:
        return {"findings": []}  # nothing in scope; skip the integration pass entirely
    prompts = [build_file_prompt(p, file_diff(base, head, p)) for p in files]
    prompts.append(build_integration_prompt(files, full_diff(base, head, files)))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        results = list(pool.map(runner, prompts))
    return merge_findings(results)


def main(argv: list[str]) -> int:
    # usage: run_review.py <base_ref> <head_ref> <out.json>
    base, head, out = argv[1], argv[2], argv[3]
    findings = collect_findings(base, head)
    Path(out).write_text(json.dumps(findings, indent=2))
    print(f"wrote {len(findings['findings'])} finding(s) to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
