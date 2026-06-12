# CI: automated PR review with Claude Code (SA-27)

Every PR is reviewed by an **independent** `claude -p` instance — separate from any
session that wrote the code — which posts actionable, low-false-positive findings as PR
comments. Re-runs report only new/unaddressed issues.

## Pipeline
```
.github/workflows/claude-review.yml      # triggers on pull_request
  └─ ci/run_review.py  base head out     # per-file passes + 1 integration pass
        └─ claude -p --output-format json --json-schema ci/review_schema.json
  └─ ci/post_comments.py out repo pr      # filter report-vs-skip, dedup, post
```

- **Non-interactive:** `claude -p` (print mode) never opens a REPL, so the job can't hang;
  the job also has `timeout-minutes: 15` as a hard stop.
- **Machine-parseable:** `--output-format json` + the schema in `ci/review_schema.json`
  yield findings with `file, line, category, severity, issue, suggested_fix,
  detected_pattern`.
- **Per-file + integration:** `run_review.py` reviews each changed file alone, then runs
  one integration pass over the whole diff for cross-file issues (broken call sites,
  changed return shapes, ordering).

## What gets reported
Defined explicitly in [`.claude/standards/review-criteria.md`](../.claude/standards/review-criteria.md)
(imported into `CLAUDE.md`, so the reviewer loads it):
- **REPORT:** `bug`, `security`, `correctness-test`, `breaking-change`.
- **SKIP:** `style`, `nit`, `subjective` (ruff and humans own those), and any `low` severity.
- The reviewer is told to default to **not** reporting when unsure — a false positive is
  worse than a miss.

## Independence & re-runs (no duplicate noise)
- The CI reviewer is a fresh instance; it does not inherit any generating session's context.
- Each posted comment embeds a hidden key (`detected_pattern::file::line`). On re-run,
  `post_comments.py` reads prior comments, recovers those keys, and posts **only** findings
  not already on the PR — so pushing fixes doesn't repost old findings.

## Dismissals (tuning false positives)
- Every finding carries a stable `detected_pattern`. To permanently suppress a noisy rule,
  add its pattern to [`ci/dismissed_patterns.json`](../ci/dismissed_patterns.json);
  `filter_reportable` drops those before posting.

## Test generation
`run_review.build_testgen_prompt(path, existing_test_files)` builds a prompt that **reads
the existing tests first and skips already-covered scenarios**, emitting offline-only tests
that follow `.claude/rules/testing.md`. Wire it into a manual or scheduled job the same way
as the review step.

## Setup
- Repo secret **`ANTHROPIC_API_KEY`** — used by `claude -p`.
- `GITHUB_TOKEN` (auto-provided) with `pull-requests: write` — used to post comments.

## Local dry run
```bash
python ci/run_review.py origin/main HEAD findings.json   # needs claude CLI + ANTHROPIC_API_KEY
python ci/post_comments.py findings.json OWNER/REPO 123  # needs gh auth
```

## Status / caveats
- The decision logic (report-vs-skip, dedup, comment round-trip, command vector, per-file +
  integration orchestration) is covered by offline unit tests in `tests/test_ci_review.py`
  (no `claude`/`gh`/network).
- The **live** `claude -p` invocation and GitHub posting are **not** exercised in CI here —
  they need the `ANTHROPIC_API_KEY` secret and a real PR. Confirm the exact reviewer flags
  (`--output-format json`, `--json-schema`) against your installed Claude Code version on
  first run; `build_command()` centralizes them if a flag name differs.
