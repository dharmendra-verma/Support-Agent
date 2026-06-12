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
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("review_schema.json")
CRITERIA_REF = ".claude/standards/review-criteria.md"

# Correctness review targets source code; reviewing docs/yaml/json for "bugs" is
# noise and burns CI time. Keep to Python.
CODE_SUFFIXES = (".py",)

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


def _criteria_clause() -> str:
    return (
        f"Apply the review criteria in {CRITERIA_REF}: REPORT only bug, security, "
        "correctness-test, and breaking-change findings; SKIP style/nit/subjective "
        "(ruff and humans own those). Default to NOT reporting when unsure — a false "
        "positive is worse than a miss. Each finding needs a stable detected_pattern key. "
        "Return JSON matching ci/review_schema.json; return an empty findings array if clean."
    )


def build_file_prompt(path: str) -> str:
    return (
        f"Review the changes to `{path}` in this PR for correctness defects only.\n\n"
        f"{_criteria_clause()}"
    )


def build_integration_prompt(paths: list[str]) -> str:
    listed = ", ".join(f"`{p}`" for p in paths) or "(none)"
    return (
        "Integration pass: review how the changed files interact — broken call sites, "
        "changed return shapes, ordering/timing dependencies, and contracts that span "
        f"files. Changed files: {listed}.\n\n{_criteria_clause()}"
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


def build_command(prompt: str, schema_path: Path = SCHEMA_PATH) -> list[str]:
    """The non-interactive reviewer invocation. `-p` = print mode (no REPL → no hang)."""
    cmd = ["claude", "-p", prompt, "--output-format", "json"]
    if schema_path is not None:
        cmd += ["--json-schema", str(schema_path)]
    return cmd


def run_claude(prompt: str, schema_path: Path = SCHEMA_PATH) -> dict:
    """Invoke the reviewer and parse its JSON. Isolated so tests don't spawn the CLI."""
    proc = subprocess.run(build_command(prompt, schema_path), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"claude review failed ({proc.returncode}): {proc.stderr.strip()}")
    return json.loads(proc.stdout)


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
    prompts = [build_file_prompt(p) for p in files]
    prompts.append(build_integration_prompt(files))
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
