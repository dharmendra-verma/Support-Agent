# Evaluation harness (SA-30)

Week-4 iteration depends on numbers: is the agent hitting the 80% first-contact-resolution
target, escalating correctly in **both** directions, routing the right tools, and extracting
accurately? This harness produces those metrics from a scripted scenario suite plus an
independent LLM-as-judge. Exam: D4 TS 4.1/4.6, D5 TS 5.5. Code: `eval/`. Tests:
`tests/test_eval_harness.py`.

## Pieces

- **`eval/scenarios/`** — 30 scripted conversations across five categories (8 standard,
  6 multi-concern, 5 policy-gap, 5 demand-human, 6 error-injection). Each declares its
  ground-truth expectations (resolved? escalated? expected tools? extraction labels). The
  error-injection scenarios carry **structured** fault config (`inject_errors`: `(tool, error
  category)` pairs), not freeform message text — so the harness makes a tool *actually* fail and
  the agent hits the real tool-error path, rather than reading "[backend down]" as customer text.
- **`eval/harness.py`** — `run_suite(agent_fn)` drives the scripted customer simulator against
  an injected agent and `compute_metrics` scores the suite:
  - **first-contact-resolution rate** over the *resolvable* scenarios (escalation cases don't
    dilute it);
  - **correct-escalation rate** as a full confusion matrix — surfacing both **missed**
    escalations (fn) and **over**-escalations (fp);
  - **tool-routing accuracy** (expected tools ⊆ used);
  - **extraction accuracy by (doc_type, field)**, reusing the SA-20 segmented report.
- **`eval/judge.py`** — an independent judge scores each conversation against an **explicit
  PASS/FAIL rubric with examples** (never "rate 1-10"): `addressed_all_concerns`,
  `no_fabrication`, `correct_handoff`, `accurate_facts`. `build_judge_prompt` includes only the
  transcript + rubric — **no generation context** — so the judge is independent. The default is
  a deterministic stand-in; a real judge is injected via `judge_fn` (a single-shot Claude
  Messages-API call per the two-path rule).
- **`eval/report.py`** — `to_json` and `render_markdown` (headline metrics with the 80% target
  call-out, the escalation confusion matrix, per-category breakdown, extraction worst-segments,
  and the judge summary).

`agent_fn` and `judge_fn` are injected, so the whole harness runs offline against fake agents.

## One full iteration (gap → change → measured improvement)

**Gap.** Baseline agent **v1** under-escalated: it silently "resolved" out-of-policy
**policy-gap** cases (e.g. a $5000 refund) instead of escalating. Running the suite:

| metric | v1 (before) | v2 (after) |
| --- | --- | --- |
| correct-escalation rate | **83%** | **100%** |
| missed-escalation rate | **31%** | **0%** |
| independent-judge pass rate | **83%** | **100%** |
| first-contact resolution | 100% | 100% |

**Change.** The escalation criterion was tightened so a request with no covering policy is
handed off rather than auto-approved (v2 escalates policy-gap cases). This is the
deterministic-gate spirit of SA-16: never fabricate an approval the policy doesn't support.

**Result.** Missed escalations went **31% → 0%** and the independent judge's pass rate rose
**83% → 100%**, with FCR unchanged (the change only affected cases that should never have been
"resolved"). This gap→change→improvement loop is asserted in
`test_one_full_iteration_shows_measured_improvement`.

## How to run

```bash
PYTHONPATH=src python -m pytest tests/test_eval_harness.py -q
```
