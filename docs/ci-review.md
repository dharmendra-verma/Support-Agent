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

- **Non-interactive & headless:** `claude -p` (print mode) never opens a REPL, and
  `--permission-mode bypassPermissions` is passed so tool use never blocks on an approval
  prompt (the cause of an early CI hang). The reviewer is also fed the **diff inline in the
  prompt** and told not to use tools, so it needs no file access at all. Each call is bounded
  by a per-call timeout, and the job has `timeout-minutes: 20` as a final backstop.
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

## Enabling / disabling (opt-in flag)
Auto-review is **off by default** and runs only when the repo variable
`ENABLE_CLAUDE_REVIEW` is `true` (job-level `if:` gate):
```bash
gh variable set ENABLE_CLAUDE_REVIEW --body true    # enable on all PRs
gh variable set ENABLE_CLAUDE_REVIEW --body false   # disable (or delete the variable)
```
Toggle in the UI under **Settings → Secrets and variables → Actions → Variables**.

## Model
Reviewer model is **Sonnet** by default (`REVIEW_MODEL`, read by `run_review.py`).
Override repo-wide without code changes:
```bash
gh variable set REVIEW_MODEL --body opus     # or haiku, or a full model id
```

## Setup
- **Auth (pick one):**
  - **`CLAUDE_CODE_OAUTH_TOKEN`** *(preferred)* — `claude -p` draws from your Max/Pro
    subscription quota (zero marginal API cost). Generate with `claude setup-token`, store
    as a repo secret. Token lifecycle/rotation: `docs/claude-code-setup.md` §6.
  - **`ANTHROPIC_API_KEY`** *(fallback)* — per-token Console billing; uncomment its line in
    the workflow for shared/team CI that shouldn't ride a personal subscription.
- `GITHUB_TOKEN` (auto-provided) with `pull-requests: write` — used to post comments.
- Repo variable **`ENABLE_CLAUDE_REVIEW=true`** to turn the review on (see above).

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
