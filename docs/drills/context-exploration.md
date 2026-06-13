# Context-efficient large-codebase investigation (SA-33)

Hands-on practice for **CCA-F D5 TS 5.4** (context management in large-codebase exploration)
and **D3 TS 3.4** (plan mode vs direct execution). The skill being drilled: keeping the main
session's context small by **isolating verbose discovery in a subagent**, and choosing the
right **session strategy** (resume / fresh+summary / fork) and **execution mode** (plan vs
direct) for the task.

The codebase under investigation is ResolveDesk itself — now **~60 files / ~3,100 lines of
`src/` + `mcp_server/` + tests** — large enough that reading it all into one context to answer a
cross-cutting question is wasteful. The same technique scales to a 50–100-file OSS repo.

---

## Drill 1 — Isolate discovery with the **Explore subagent**

**Task (genuinely cross-cutting):** *trace end-to-end how a refund is enforced against the
auto-approval threshold — every layer, the constant, the invariant per layer, and the tests.*

**What I did:** dispatched the **Explore subagent** with that question (medium breadth) and an
explicit instruction to return **only a ~25-line structured summary**, not file contents. The
subagent read ~8–10 files in **its own** context and returned this:

> **Enforcement layers (ordered):**
> 1. SDK loop — `src/agent/sdk_agent.py:build_options` wires hooks into `ClaudeAgentOptions`
> 2. PreToolUse hook gate — `src/agent/hooks.py:refund_threshold_decision` / `pre_tool_use_hook`
> 3. MCP tool handler — `mcp_server/server.py:process_refund` (secondary validation)
> 4. Backend persistence — `mcp_server/backend.py:Backend.record_refund` (persists only auto-approved)
> 5. Policy resource — `mcp_server/resources.py:refund_policy` (published single source of truth)
>
> **Threshold:** `REFUND_AUTO_APPROVE_LIMIT = 500.0` at `mcp_server/backend.py:14`, imported as
> `REFUND_LIMIT` in `hooks.py:20`.
>
> **Invariant per layer:** hook denies >$500 + redirects to `escalate_to_human` (handler never
> runs); tool returns `requires_approval` over limit; backend persists only when `amount <= 500`;
> policy resource publishes the "$500 auto-approve" rule so the model never guesses.
>
> **Tests:** `test_hooks.py` (incl. `test_30_run_threshold_blocks_100_percent` — 0/30 leaks),
> `test_tool_routing.py` (over-limit not persisted), `test_gates.py` (verify-gate + threshold).

**Verify, don't trust blindly.** The summary placed `build_hooks_config` in `sdk_agent.py`; a
single cheap `Grep("build_hooks_config")` showed it actually lives at **`hooks.py:142`**. The
main session confirms a subagent's load-bearing claims with one targeted search — far cheaper than
having read every file itself.

**Why a subagent here:** the discovery touched ~900 lines across 8–10 files. Done inline, all of
that verbose tool output would sit in the main context permanently. The Explore subagent absorbs
it and hands back ~30 lines — the main session keeps the *conclusion*, not the file dumps.

---

## Drill 2 — Context budget log (with vs without Explore isolation)

Estimated at ~4 chars/token (the harness uses the same heuristic in `eval/trimming.py`):

| Approach | What enters the **main** context | ~Tokens |
|---|---|---|
| **Read-everything inline** | the 8–10 files the question spans (~900 lines) | **~9,000** |
| **Explore subagent isolation** | the returned ~30-line summary only | **~350** |
| **Savings** | discovery stays in the subagent | **~96% fewer main-context tokens** |

The subagent *does* spend the ~9k tokens — but in a **disposable context** that's discarded after
it answers. The main session, which has to stay alive for the whole task, pays ~350. That's the
whole point of TS 5.4: spend throwaway context on discovery, preserve durable context for work.

**Rule:** if answering a question requires reading more than ~2–3 files of verbose output you
won't edit, send an Explore subagent and keep only its summary.

---

## Drill 3 — Session-strategy decision rules

Mapped to the real session layer (`src/agent/sessions.py`, SA-9):

| Situation | Choice | Why / API |
|---|---|---|
| Prior context still valid; you just learned which files changed | **`--resume <name>`** | continue the same session; `Session.inform_changes([...])` injects a targeted "these changed → re-analyze only what's affected" notice so the agent doesn't redo everything |
| Prior **tool results are stale** (order status/balance moved on) | **fresh session + structured summary** | resuming would replay OLD tool output as if current → wrong answer. `continue_session()` detects staleness via `is_stale()` and starts fresh seeded only with the durable `CaseSummary.to_prompt()` (volatile snapshots dropped, must be re-fetched) |
| Compare **two refactoring approaches** from one baseline | **`fork_session`** | `SessionStore.fork(name, new_name)` deep-copies a baseline into an independent session; mutating the fork never affects the original (`ClaudeAgentOptions(resume=id, fork_session=True)`) — run approach A and approach B from identical starting context, then diff |

The trap the exam tests: **resuming a session whose tool results are stale.** The fix is not "summarize harder" — it's a fresh session seeded with the *durable* facts only, forcing a re-fetch of anything volatile.

---

## Drill 4 — Plan mode vs direct execution

**Plan mode → one architectural / multi-file change.** Example shape from this backlog: building
the multi-agent orchestration (SA-21) touched a new `src/research/` package, the coordinator,
agent specs, tests, and `pyproject.toml`. The right move is **plan first**: enumerate the files,
agree the decomposition and the public surface, then execute — because a wrong abstraction
discovered after writing five files is expensive to unwind. Plan mode keeps the exploration and
proposal in front of the user before any edit lands.

**Direct execution → one scoped fix.** Example: the CI reviewer flagged that
`run_research` overwrote multi-gap findings under one key. The fix was a single keying change in
one function plus a regression test — **no plan needed**; reading the function, making the edit,
and running the test is faster than proposing a plan for a localized change.

**Rationale rule:** plan mode when the change is *multi-file, architectural, or hard to reverse*
and the cost of a wrong direction is high; direct execution when the change is *localized,
well-understood, and cheaply verifiable by a test*.

---

## Decision cheat sheet

| Question | Answer |
|---|---|
| Discovery would dump many files into context? | **Explore subagent**, keep the summary |
| Subagent made a load-bearing claim? | **Grep to verify** — one search, not a re-read |
| Prior context valid, files changed? | **`--resume`** + `inform_changes` |
| Prior tool results stale? | **fresh session** + durable `CaseSummary` only |
| Comparing two approaches from a baseline? | **`fork_session`** |
| Multi-file / architectural / irreversible? | **plan mode** |
| Localized, test-verifiable fix? | **direct execution** |
