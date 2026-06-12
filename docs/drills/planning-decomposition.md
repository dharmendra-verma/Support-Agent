# Planning & decomposition drills (SA-34)

Hands-on drills for **plan mode vs direct execution** (D3 TS 3.4), **iterative refinement**
(D3 TS 3.5), and **dynamic adaptive decomposition** (D1 TS 1.6, open-ended half). Every
exercise is anchored to a concrete ResolveDesk task so the judgment is real, not abstract.

> How to run live: in Claude Code, press **Shift+Tab** to toggle **plan mode** (Claude
> investigates and proposes a plan without editing), approve/iterate, then execute. Capture
> one transcript per drill. The classifications and rationale below are the answer key.

---

## Drill 1 — Plan mode vs direct execution (decision drill)

**Use plan mode when** scope is unknown, the change spans many files or is architectural,
the blast radius is high, or requirements are ambiguous and need exploration first.
**Use direct execution when** the task is scoped, well-understood, low-risk, and you can
name the exact edit up front.

| # | Task (mostly ResolveDesk-anchored) | Mode | Rationale (exam criteria) |
|---|---|---|---|
| 1 | Add a date-validation guard to one function given a stack trace | **Direct** | Single file, exact location known from the trace, low risk |
| 2 | Wire `pause_turn` handling into `loop.py` (deferred SA-8 item) | **Direct** | Localized to one `stop_reason` branch; the fix is already specified |
| 3 | Rename a variable in `loop.py` and update references | **Direct** | Mechanical, bounded, tool-verifiable |
| 4 | Fix an off-by-one with a failing test already written | **Direct** | Repro exists; change is one expression |
| 5 | Split `loop.py`/`sdk_agent.py` into a packaged module layout | **Plan** | Architectural, many imports/callers move, needs a sequence |
| 6 | Migrate 45 files from `anthropic` v1 → v2 SDK | **Plan** | Broad surface; needs a strategy + per-file verification + rollback |
| 7 | Add a persistent case-facts context layer across the agent (SA-28) | **Plan** | Cross-cutting; touches loop, client, sessions; design choices first |
| 8 | Build multi-agent research orchestration (SA-21) | **Plan** | Novel, high-risk, unknown decomposition — explore before building |
| 9 | Add one MCP tool following the existing registry pattern (SA-10) | **Direct** | Established pattern; one handler + schema + registration |
| 10 | Add token-usage caching to cut cost across the agent | **Plan** | Multiple touchpoints + design trade-offs (where/what to cache) |

**Tell:** if you can write the diff in your head, execute. If you'd first have to *go read
the code to know what the diff even is*, plan.

---

## Drill 2 — Adaptive decomposition (anchor: test `ci/post_comments.py`)

Task: *"add comprehensive tests to this module."* A **fixed pipeline** would blindly write
one test per function. **Adaptive decomposition** maps the terrain first and lets the plan
change as it learns:

1. **Map structure** — `post_comments.py` has pure logic (`filter_reportable`, `finding_key`,
   `select_new`, `extract_posted_keys`, `reportable_new`, `format_comment`, `load_findings`)
   and an I/O shell (`gh_*`, `main`).
2. **Identify high-impact areas** — the pure report-vs-skip + dedup logic is where bugs hurt
   (wrong findings posted / re-posted). Prioritize those.
3. **Plan — then adapt:**
   - *Discovery A:* the `gh_*` functions need a live PR → **adapt:** don't unit-test them;
     cover only pure functions, isolate I/O behind the shell. (This is exactly why the real
     suite tests logic, not `gh`.)
   - *Discovery B:* `format_comment` embeds a key that `extract_posted_keys` must recover →
     **adapt:** add a round-trip test (write → parse), not two isolated tests.
   - *Discovery C:* re-runs must not re-post → **adapt:** add a dedup-vs-already-posted test.
4. **Result** — a risk-ordered test set, not a uniform one-per-function sweep. Contrast: the
   fixed pipeline wastes effort on trivial getters and misses the round-trip/dedup edges.

**Lesson:** the plan is a *living* artifact; each discovered dependency reshapes the next step.

---

## Drill 3 — Iterative refinement (anchor: this project's SA-27 CI reviewer)

A real **generate → evaluate → refine** loop that actually happened building the CI reviewer:

| Pass | Generate | Evaluate | Refine |
|---|---|---|---|
| 1 | Per-file `claude -p` review, full diff, `--json-schema` | CI **hung** 15→20 min (zero output) | parallelize, scope to `.py`, raise timeout |
| 2 | Add `bypassPermissions`, `--max-turns 1`, `stdin=DEVNULL` | still hung 240s/call; `partial output: ''` | **smoke test** to isolate CLI vs prompts |
| 3 | Trivial `claude -p` smoke call | returned in **1.9s** → CLI fine; diff was `--json-schema` + result-envelope | drop `--json-schema`; parse `.result` envelope |
| 4 | Real review run | completed, but **0 findings** (clean diff) | plant a canary bug to exercise posting |
| 5 | Review with canary | **caught the canary + a real bug** in our own code; posted comments | fix the real bug; remove canary |

**Stopping criterion:** the deliverable met its acceptance test — the reviewer posts real
findings end-to-end (planted *and* genuine), with filtering and dedup firing. Each pass
changed exactly one variable so the next evaluation was attributable; we stopped when the
behavior matched the AC, not when we ran out of ideas.

---

## Drill 4 — Prompt chaining vs adaptive decomposition (contrast)

| | Prompt chaining (fixed) | Adaptive decomposition |
|---|---|---|
| Shape | Predetermined stages, every run | Plan evolves as structure/deps are discovered |
| Example | SA-27 review: per-file pass → integration pass, always | Drill 2: test plan reshaped by each discovery |
| Use when | Steps are known up front; items independent/uniform | Scope unknown; the *right* steps aren't knowable until you look |
| Failure if misused | Chaining an open-ended task → misses what you couldn't foresee | Adapting a known task → wasted exploration overhead |

**Rule of thumb:** known, repeatable shape → **chain**. Unknown shape that you must discover →
**decompose adaptively** (and start in plan mode). SA-27's reviewer is a chain *inside* a
project that was itself built by adaptive decomposition — the two compose.

---

## Exam mapping
- **D3 TS 3.4** — Drill 1 (plan vs direct decision criteria).
- **D3 TS 3.5** — Drill 3 (generate→evaluate→refine, explicit stopping criterion).
- **D1 TS 1.6 (open-ended)** — Drill 2 + Drill 4 (adaptive decomposition vs fixed pipeline).
