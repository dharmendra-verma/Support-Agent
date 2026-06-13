# Anti-pattern recognition drills (SA-37)

The CCA-F tiebreaker questions are decided by recognising an anti-pattern on sight and reaching
for the meta-principle that fixes it. This deck drills the **seven anti-patterns**, each paired
with the meta-principle it violates and a **concrete example from the ResolveDesk codebase** (the
right pattern, contrasted with the wrong one). Cross-domain (D1–D5).

---

## Part 1 — Seven anti-patterns (flashcards)

Cover the right column; name the principle and the fix from the anti-pattern alone.

### 1. Prompt-where-code-is-needed → **programmatic > prompt-based**
- **Anti-pattern:** enforce a hard policy by *asking* the model ("never approve a refund over
  $500"). The model can be argued out of it; enforcement is probabilistic.
- **Right (ResolveDesk):** the $500 limit is a **deterministic PreToolUse hook**
  (`src/agent/hooks.py:refund_threshold_decision`) that blocks `process_refund` before any
  handler runs — proven by `test_30_run_threshold_blocks_100_percent` (0/30 leaks).
- **Tell:** "instruct the model to always/never X" where X is a safety/policy invariant → wrong.
  Put the invariant in code.

### 2. Disproportionate first step → **proportionate first step**
- **Anti-pattern:** reach for a multi-agent system / fine-tune / RAG stack when one tool call or
  a single prompt would do.
- **Right (ResolveDesk):** `src/agent/loop.py` is a plain `stop_reason` loop; verification is one
  programmatic gate (`gates.py`), not an orchestrator. Multi-agent (`src/research/`) appears only
  where the task genuinely fans out (SA-21).
- **Tell:** the heaviest option that *could* work is rarely the answer; pick the smallest that
  fully solves it.

### 3. Over-broad tools / capabilities → **least privilege**
- **Anti-pattern:** hand every agent the full toolset "to be safe".
- **Right (ResolveDesk):** `ROLE_TOOLS` scopes each role to ≤5 tools (`tooling.py`); the research
  coordinator's only tool is `Task`; subagents get minimal, role-scoped sets (`research/agents.py`).
  Selection reliability degrades past ~5 tools — fewer is *more* correct, not just safer.
- **Tell:** "give the agent access to all tools" → wrong; scope to the role.

### 4. Implicit / assumed context → **explicit context**
- **Anti-pattern:** assume a subagent or a resumed session can see context it was never given.
- **Right (ResolveDesk):** subagents **inherit nothing** — every subtask prompt is self-contained
  (`research/coordinator.py`); durable case facts are **prepended explicitly** outside summarized
  history (`agent/case_facts.py`, SA-28); a stale session starts fresh seeded with a `CaseSummary`
  rather than replaying old tool output.
- **Tell:** "the subagent will know about…" → it won't; state it in the prompt.

### 5. Bare / swallowed errors → **structured errors**
- **Anti-pattern:** return a generic "operation failed", or mask a failure as an empty success
  ("no records found").
- **Right (ResolveDesk):** `mcp_server/errors.py` returns a typed `ToolError` envelope (category +
  `isRetryable` + customer-safe message); `research/errors.py` propagates a `SubagentReport`
  (failure type, attempted query, partial results, alternatives) and keeps **valid-empty distinct
  from access-failure**.
- **Tell:** an error path that returns `None`/`[]`/"failed" with no category or retry signal → wrong.

### 6. Self-review / no independent check → **independent review**
- **Anti-pattern:** the author (or the generating instance) reviews its own work; or control flow
  decided by parsing the model's "I'm done" prose.
- **Right (ResolveDesk):** the CI reviewer is a **second, independent instance** with no generator
  context (`ci/run_review.py`, `src/review/pipeline.py`, SA-27/35) — it caught real bugs the author
  missed (SA-21 overwrite, SA-22 false corroboration). Termination is driven by `stop_reason` /
  `ResultMessage`, never by prose (`agent-architecture.md`).
- **Tell:** "have the same agent check its answer" or "stop when the model says it's finished" → wrong.

### 7. Wrong API-to-latency matching → **API-to-latency matching**
- **Anti-pattern:** use a synchronous, interactive call for a bulk offline job (or vice-versa);
  run independent work serially.
- **Right (ResolveDesk):** the historical-ticket backlog goes through the **Message Batches API**
  (`extraction/batch.py`, SA-19 — async, ~50% cheaper, no latency need); interactive support uses
  the synchronous Messages API; independent research subtasks fan out **in parallel** in one
  response (`research/coordinator.py:latency_seconds`, SA-21).
- **Tell:** "stream a 50k-ticket reprocess to the user" → wrong (batch it); "batch the live chat
  turn" → wrong (sync it).

---

## Part 2 — Distractor-spotting drill (10 questions)

For each, the correct answer **and why each wrong option is wrong** (named failure type).

**Q1.** Enforce "refunds over $500 need a human" for an agent. Best approach?
- ✅ A deterministic pre-tool gate that blocks the call. → correct (programmatic > prompt).
- ❌ Add "never auto-approve over $500" to the system prompt. → *prompt-where-code-needed*.
- ❌ Fine-tune a model on refund decisions. → *disproportionate first step*.
- ❌ Have the agent double-check itself after approving. → *self-review*; also too late (money moved).

**Q2.** A research coordinator needs to investigate 4 independent sources. First move?
- ✅ Spawn 4 subagents in parallel in one response. → correct (parallel fan-out; latency = slowest one).
- ❌ Ask one agent to research all four sequentially. → *API-to-latency mismatch* (serial when parallel is free).
- ❌ Give one agent all source tools and a long prompt. → *over-broad tools* + context bloat.
- ❌ Build a fine-tuned router first. → *disproportionate first step*.

**Q3.** A subagent must analyse an attached invoice. What goes in its prompt?
- ✅ The full task, the document, and the quality bar — self-contained. → correct (explicit context).
- ❌ "Continue the analysis from the coordinator's findings." → *implicit context* (it inherits nothing).
- ❌ All 18 tools in case it needs them. → *over-broad tools* (selection degrades).
- ❌ "Summarize when you feel done." → vague stop; *prose-driven completion*.

**Q4.** A tool call to the order service times out. Return to the agent?
- ✅ A structured error: category=transient, isRetryable=true, message. → correct (structured errors).
- ❌ An empty result list. → *swallowed error* → confidently-wrong "no orders".
- ❌ `raise` and crash the turn. → *unstructured failure*; loses the recoverable path.
- ❌ "Something went wrong." → *bare error*, nothing to act on.

**Q5.** Reprocess 50,000 historical tickets for extraction. Which API?
- ✅ Message Batches API (async). → correct (no latency need, ~50% cheaper).
- ❌ Synchronous Messages API, streamed. → *API-to-latency mismatch* (interactive path for a bulk job).
- ❌ The Agent SDK loop per ticket. → *disproportionate* + serial latency.
- ❌ Fine-tune for extraction first. → *disproportionate first step*.

**Q6.** Decide when the agent loop should stop.
- ✅ On `stop_reason == end_turn` / the `ResultMessage`. → correct (programmatic control flow).
- ❌ When the model writes "I'm done." → *prose-driven completion*.
- ❌ After a fixed 25 iterations. → cap is a *safety net*, not the primary stop.
- ❌ When the last tool returned successfully. → wrong; the model may still need more turns.

**Q7.** Review a 12-file PR. Best setup?
- ✅ An independent instance, per-file passes + a cross-file integration pass. → correct.
- ❌ The author re-reads their own diff. → *self-review* (anchored to intent).
- ❌ One pass over all 12 files concatenated. → misses local bugs; no separation.
- ❌ Trust the tests; skip review. → tests encode the author's assumptions too.

**Q8.** A triage agent only ever looks up orders and refund status. Its toolset?
- ✅ Just those 2–3 tools. → correct (least privilege).
- ❌ All MCP tools, filtered by a prompt instruction. → *prompt-where-code-needed* + *over-broad*.
- ❌ The refund + escalation tools as well "for flexibility". → *over-broad tools*.
- ❌ A single mega-tool that does everything. → poor selection + blast radius.

**Q9.** Long support chat; the agent must recall an exact $49.99 from turn 2 at turn 30.
- ✅ A persistent case-facts block prepended outside summarized history. → correct (explicit context).
- ❌ Rely on the rolling summary. → *implicit context*; summarization blurs exact figures.
- ❌ Increase the context window and read it all each turn. → *disproportionate* + lost-in-the-middle.
- ❌ Ask the customer to repeat it. → offloads a solvable state problem.

**Q10.** A flaky third-party call fails intermittently inside a subagent.
- ✅ Retry transient failures locally; propagate only unresolvable ones as structured data. → correct.
- ❌ Let the exception kill the whole research run. → *workflow-death* anti-pattern.
- ❌ Return an empty success so the coordinator moves on. → *fake empty success*.
- ❌ Add "please be reliable" to the prompt. → *prompt-where-code-needed*.

---

## Part 3 — One-page meta-principles cheat sheet (day-before review)

| Principle | One-liner | Reach for it when the question is about… |
|---|---|---|
| **Programmatic > prompt-based** | Enforce invariants in code, not instructions | safety/policy gates, "always/never" rules |
| **Proportionate first step** | Smallest thing that fully solves it | "what's the FIRST/BEST approach" |
| **Least privilege** | Scope tools/permissions to the role (~≤5 tools) | tool distribution, subagent capabilities |
| **Explicit context** | Hand over everything; assume nothing inherited | subagents, resumed/forked sessions, long chats |
| **Structured errors** | Category + retryable + message; empty ≠ failure | tool failures, timeouts, partial results |
| **Independent review** | A second instance, no generator context; `stop_reason` not prose | review setup, loop termination |
| **API-to-latency matching** | Batch offline & bulk; sync interactive; parallelise independent | which API / serial-vs-parallel |

**Exam-day reflexes:**
- No penalty for guessing — **answer every question**.
- The most powerful/complex option is usually a distractor (*disproportionate first step*).
- "Tell the model to…" for an invariant is almost always wrong (*prompt-where-code-needed*).
- "It will already know / see…" about a subagent is wrong (*implicit context*).
- Pass bar is **720/1000** scaled — aim comfortably above on mocks.
