# Multi-pass independent review pipeline (SA-35)

Why a *second* Claude instance reviewing a diff beats the author self-reviewing, and why a
large change needs **per-file passes plus a cross-file integration pass**. Exam: D4 TS 4.6.
Code: `src/review/passes.py`, `src/review/pipeline.py`. Tests: `tests/test_review_pipeline.py`.

## The pipeline

`run_pipeline(files, review_fn=…)`:

1. **Per-file pass** for every changed file — local analysis in isolation (inverted conditions,
   off-by-one, None deref, swallowed errors). Cheap, parallelisable.
2. **Integration pass** — *one* cross-file pass over all changed files together, for the bugs no
   single-file pass can see: data-flow breaks, **contract mismatches** (a changed callee vs its
   callers), ordering dependencies. Run **only when the change is large** (≥2 files and ≥
   `min_lines_for_integration`), so small diffs don't pay pass-splitting overhead
   (`needs_integration_pass`).

The reviewer is **injected** (`review_fn`). In production it's a **second, independent
`anthropic` client session** (`build_review_fn`) — an instance with **no access to the
generator's reasoning**, given only the diff. The prompts (`passes.py`) state that independence
explicitly: *"You did NOT write this change and have NO access to the author's intent — judge
what the code does, not what it was meant to do."*

## Confidence-calibrated routing

Every `Finding` self-reports a `confidence` (0–1). `route(findings, auto_threshold=0.8)` splits
them: high-confidence → **auto-report**, low-confidence → **human triage** — false positives
destroy trust in automated review (review-criteria.md), so uncertain findings aren't posted
blindly. This is the SA-20 confidence-routing idea applied to code review.

## Why independence beats self-review (demonstrated)

`test_independent_reviewer_catches_what_self_review_missed` runs the **same diff** through two
reviewers: a self-review that rationalises its own bug away (returns nothing) and an independent
instance that reports the `division by zero`. Same code, different outcome — the independent
instance isn't anchored to the author's intent.

This isn't only a unit test — it's the **lived experience of this whole project**. The CI
reviewer (SA-27) is exactly such an independent instance, and at Definition-of-Done it caught
defects the generator (me) had written and not seen:

| Story | What the independent reviewer caught | Pass type it maps to |
|---|---|---|
| **SA-21** | `run_research` keyed multi-gap findings by role, so several gap subtasks overwrote each other — only the last survived to synthesis | **per-file** (local logic bug in one function) |
| **SA-22** | a valueless source was counted as corroboration for another source's value → false `ESTABLISHED` | **per-file** (local logic bug) |
| **SA-30** | error-injection encoded as message **text** while the harness expected structured config, and `expected_tools` under-specified the refund pre-flight across scenario + metrics | **integration** (contract mismatch spanning scenario defs ↔ harness) |

Each was fixed with a regression test before merge. That's the two-real-stories bar met several
times over.

## Wiring into Definition-of-Done

`git-workflow.md` requires an independent review to pass before merge. The CI workflow
(`.github/workflows/claude-review.yml` → `ci/run_review.py`, SA-27) is that gate today; this
library is its generalised, unit-tested form — same independent-instance principle, now with
explicit per-file vs integration passes and confidence routing that a CI step or a local
pre-merge check can call directly:

```python
from review.pipeline import run_pipeline, build_review_fn, route
report = run_pipeline(changed_files, review_fn=build_review_fn("sonnet"))
post = route(report.by_severity())          # auto_report now, triage the rest
```

## How to run the tests

```bash
PYTHONPATH=src python -m pytest tests/test_review_pipeline.py -q
```
