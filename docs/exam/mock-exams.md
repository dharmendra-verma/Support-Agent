# Week-4 timed mock exams (SA-36)

Two timed mock runs for the CCA-F, built to the exam's shape. **These are practice materials —
sitting the mocks under time and recording real scores is the candidate's job** (the score
trend and the ≥80% bar can't be pre-filled). Everything you need to self-administer and grade is
here.

> **Integrity note:** the 12 *official* sample questions are not reproduced here (Anthropic's
> material). Mock A is **original** questions written to the *same task statements* the official
> samples test; Mock B is the self-generated 4-scenarios × 5-domains set. Use the official 12
> alongside these for the full Week-4 run.

## How to take it

- **Timed:** 90 minutes per mock, one sitting, no notes (mimic exam conditions).
- **Answer everything** — no penalty for guessing.
- **Scaled scoring:** pass bar is **720/1000** (≈72%); aim for **≥80%** on the final mock before
  exam day.
- Grade with the answer key, then run the **miss → task-statement → re-drill** loop (bottom).

---

## Mock A — core task statements (15 questions, original)

**A1 (D1).** A support agent loop must decide when it's finished. The correct control signal is:
(a) the model writing "done"; (b) `stop_reason == end_turn` / the `ResultMessage`; (c) hitting
the 25-iteration cap; (d) the last tool returning success.

**A2 (D1).** A coordinator needs four independent sources investigated. The best first move:
(a) one agent loops the four serially; (b) spawn four subagents as parallel `Task` calls in one
response; (c) a fine-tuned router; (d) one agent with all four tools and a long prompt.

**A3 (D1).** When decomposing a task for subagents, each subtask prompt should specify:
(a) exact step-by-step procedures; (b) a goal + quality criteria, self-contained; (c) only the
sub-question, relying on inherited context; (d) the coordinator's full reasoning trace.

**A4 (D2).** To guarantee the agent calls *some* tool on the next turn (no chit-chat):
(a) `tool_choice={"type":"auto"}`; (b) `{"type":"any"}`; (c) `{"type":"tool","name":…}`;
(d) `{"type":"none"}`.

**A5 (D2).** Tool-selection reliability as the toolset grows from ~5 to ~18 tools:
(a) improves; (b) is unchanged; (c) degrades — scope tools per role; (d) depends only on model size.

**A6 (D2).** A tool times out. The right return to the agent:
(a) an empty result list; (b) `raise` and crash the turn; (c) a structured error (category,
isRetryable, message); (d) "something went wrong".

**A7 (D3).** Enforce "refunds over $500 require a human." Best approach:
(a) a system-prompt instruction; (b) a deterministic pre-tool gate that blocks the call;
(c) fine-tuning; (d) a post-hoc self-check by the same agent.

**A8 (D3).** A prior session's tool results are now stale (order status changed). You should:
(a) `--resume` it as-is; (b) start fresh seeded with a durable `CaseSummary`, dropping stale
snapshots; (c) increase the context window; (d) ask the customer to restate everything.

**A9 (D3).** Plan mode is the right choice for:
(a) a one-line constant change; (b) a multi-file architectural change that's costly to unwind;
(c) every change, always; (d) never — direct execution is always faster.

**A10 (D4).** An independent Claude instance reviewing a diff beats author self-review because:
(a) it's a bigger model; (b) it has no access to the author's reasoning/intent, so it judges
what the code does; (c) it runs the tests; (d) it sees more files.

**A11 (D4).** First-contact-resolution rate should be computed over:
(a) all conversations including correct escalations; (b) only the scenarios that should be
resolvable; (c) only escalations; (d) a fixed denominator of 100.

**A12 (D4).** Correct-escalation quality must be reported as:
(a) a single accuracy number; (b) both directions — missed escalations and over-escalations;
(c) only the missed rate; (d) only the false-positive rate.

**A13 (D5).** Reprocess 50,000 historical tickets for extraction. Use:
(a) the synchronous Messages API, streamed; (b) the Message Batches API (async, ~50% cheaper);
(c) the Agent SDK loop per ticket; (d) a fine-tune.

**A14 (D5).** In a long chat, recalling an exact $49.99 from turn 2 at turn 30 is best served by:
(a) the rolling summary; (b) a persistent case-facts block prepended outside summarized history;
(c) a bigger context window read every turn; (d) asking the customer.

**A15 (D5).** Two credible sources report different market sizes at different dates. Synthesis should:
(a) pick the higher one; (b) average them; (c) present both side-by-side and treat differing
values at different dates as temporal change, not a contradiction; (d) drop both.

---

## Mock B — scenario set (4 scenarios × 5 domains = 20 questions)

### Scenario 1 — Build a customer-refund agent
**B1 (D1)** First architecture move? (a) multi-agent orchestrator; (b) a single SDK agent loop
with scoped tools; (c) fine-tune; (d) a rules engine, no model.
**B2 (D2)** The refund flow must verify the customer *before* looking up the order. Enforce via:
(a) prompt ordering; (b) a forced `tool_choice` on `get_customer` first, then `any`; (c) hope;
(d) one mega-tool.
**B3 (D3)** Where does the $500 limit live? (a) system prompt; (b) a PreToolUse hook; (c) the
model's training; (d) the customer message.
**B4 (D4)** Before merging the agent, the diff is reviewed by: (a) the author; (b) an independent
instance with no generator context; (c) nobody, tests suffice; (d) the customer.
**B5 (D5)** The order service errors mid-refund. The subagent should: (a) crash the run; (b) fake
an empty success; (c) retry transient locally, else propagate a structured failure + escalate;
(d) loop forever.

### Scenario 2 — Reprocess 100k historical tickets for extraction
**B6 (D1)** Orchestration? (a) an agentic loop per ticket; (b) a batch pipeline, no agent loop;
(c) one giant prompt with all tickets; (d) a multi-agent debate.
**B7 (D2)** Extraction output is guaranteed-shaped by: (a) asking for JSON in prose; (b) a
tool/`input_schema` the model fills via tool_use; (c) regex on free text; (d) trust.
**B8 (D3)** Nullable fields in the schema exist so that: (a) the model fills everything; (b) absent
info returns null instead of being fabricated; (c) validation is skipped; (d) speed.
**B9 (D4)** Low-confidence extractions are: (a) auto-accepted; (b) routed to human review via a
calibrated threshold; (c) discarded; (d) retried forever.
**B10 (D5)** The API for this bulk, non-urgent job: (a) sync Messages, streamed; (b) Message
Batches (async, cheaper); (c) live Agent SDK; (d) websocket.

### Scenario 3 — Research competitor pricing across many sources
**B11 (D1)** Structure? (a) one agent reads everything; (b) a coordinator that fans out
role-scoped subagents and synthesizes; (c) fine-tune on pricing; (d) a single mega-prompt.
**B12 (D2)** Each subagent gets: (a) all tools; (b) only its role's minimal toolset; (c) no tools;
(d) the coordinator's tools.
**B13 (D3)** To investigate a large unfamiliar repo without exhausting context: (a) read every
file; (b) dispatch an Explore subagent and keep only its summary; (c) grep nothing, guess;
(d) open all files in tabs.
**B14 (D4)** Conflicting stats from credible sources are: (a) averaged; (b) the first one wins;
(c) shown side-by-side with attribution + a conflict annotation; (d) dropped.
**B15 (D5)** Subagent findings must carry: (a) just the claim; (b) claim + source + date
(content separated from metadata); (c) the full reasoning chain; (d) nothing structured.

### Scenario 4 — Long multi-issue support conversation
**B16 (D1)** "Refund my order, fix billing, update address" should be: (a) handled as one blob;
(b) decomposed into distinct tracked items, independents investigated in parallel; (c) refused;
(d) handled strictly serially regardless of dependencies.
**B17 (D2)** A refund item depends on the order-status item. The orchestration must: (a) run them
in parallel anyway; (b) detect the dependency and sequence it; (c) drop the refund; (d) merge them.
**B18 (D3)** Across a 30-turn chat, exact figures survive via: (a) summarization; (b) a persistent,
*updatable* case-facts block (status changes overwrite); (c) a longer window; (d) re-asking.
**B19 (D4)** Whether the agent hits its 80% FCR target is known by: (a) intuition; (b) a scenario
eval suite producing FCR + escalation metrics; (c) customer NPS only; (d) ticket volume.
**B20 (D5)** A long run crashes mid-way. It resumes without redoing work via: (a) restarting from
zero; (b) an atomically-persisted manifest of completed subtasks + findings; (c) a bigger window;
(d) luck.

---

## Answer keys

**Mock A:** A1 **b** · A2 **b** · A3 **b** · A4 **b** · A5 **c** · A6 **c** · A7 **b** · A8 **b** ·
A9 **b** · A10 **b** · A11 **b** · A12 **b** · A13 **b** · A14 **b** · A15 **c**

**Mock B:** B1 **b** · B2 **b** · B3 **b** · B4 **b** · B5 **c** · B6 **b** · B7 **b** · B8 **b** ·
B9 **b** · B10 **b** · B11 **b** · B12 **b** · B13 **b** · B14 **c** · B15 **b** · B16 **b** ·
B17 **b** · B18 **b** · B19 **b** · B20 **b**

(One-line rationale for any miss: every correct answer is the *proportionate, programmatic,
least-privilege, explicit-context, structured-error, independently-reviewed, latency-matched*
option — see `docs/exam/anti-patterns.md`. The plausible distractors are the over-engineered or
prompt-based ones.)

---

## Score tracker (fill in per attempt)

| Attempt | Date | Raw (x/35) | Scaled (/1000) | D1 | D2 | D3 | D4 | D5 | Notes |
|---|---|---|---|---|---|---|---|---|---|
| Mock A #1 |  |  |  |  |  |  |  |  |  |
| Mock B #1 |  |  |  |  |  |  |  |  |  |
| Mock A #2 |  |  |  |  |  |  |  |  |  |
| Final mock |  |  |  |  |  |  |  |  |  |

Scaled ≈ `round(raw/35 * 1000)`. **Pass = 720; target final ≥ 800.**

---

## Miss → task-statement → re-drill map

When you miss a question, map its domain to the SA story whose code re-drills the concept:

| Domain | If you missed… | Re-drill on |
|---|---|---|
| D1 | loop control / multi-agent / decomposition | `src/agent/loop.py`, `src/research/` (SA-8, SA-21) |
| D2 | tool_choice / tool distribution / MCP errors | `src/agent/tooling.py`, `mcp_server/errors.py` (SA-11, SA-13) |
| D3 | gates / hooks / sessions / plan mode | `src/agent/gates.py`, `hooks.py`, `sessions.py`; `docs/drills/` (SA-14/15/9, SA-33) |
| D4 | review / eval / escalation | `src/review/pipeline.py`, `eval/`, `src/agent/escalation.py` (SA-35, SA-30, SA-16) |
| D5 | context / batch / recovery / provenance | `src/agent/case_facts.py`, `extraction/batch.py`, `research/manifest.py`, `research/synthesis.py` (SA-28, SA-19, SA-24, SA-22) |

**The loop:** miss → identify the task statement → re-read the cited code + its doc → re-attempt
the question. A statement still weak after one re-drill gets a second pass before exam day.
