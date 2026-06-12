---
description: Run the team code-review checklist on the current branch diff.
argument-hint: [base-branch]
allowed-tools: Bash(git diff:*), Bash(git log:*), Read, Grep, Glob
---

Run the team code-review checklist on this branch.

The base branch is `$ARGUMENTS` if provided, otherwise `main`.

1. Get the diff: `git diff <base>...HEAD`.
2. Apply the criteria in @.claude/standards/review-criteria.md — REPORT only
   `bug` / `security` / `correctness-test` / `breaking-change`; SKIP style and nits
   (ruff and humans own those). Default to NOT reporting when unsure.
3. For each finding give `file:line`, a severity, and a concrete suggested fix.
4. Finish with a one-line verdict: **PASS** (nothing to fix) or **CHANGES (N)**.
