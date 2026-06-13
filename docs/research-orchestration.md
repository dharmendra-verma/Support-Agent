# Multi-agent research orchestration (SA-21)

A **coordinator** agent decomposes a research question, fans out role-scoped **subagents**
in parallel via the Agent SDK `Task` tool, and synthesises their findings — with an
iterative refinement loop that targets gaps. Exam: D1 TS 1.2/1.3/1.6, sample Q7.

Code: `src/research/agents.py` (specs) + `src/research/coordinator.py` (logic).
Tests: `tests/test_orchestration.py` (offline, injected fakes — no SDK, no network).

## The two tiers

| Tier | Role | Tools | Why |
|---|---|---|---|
| Coordinator | plan + delegate, never research | **`Task` only** | one job: decompose and fan out |
| `web_search` | external/public info | `WebSearch`, `WebFetch` | current state of the world |
| `doc_search` | internal KB grounding | `Grep`, `Read`, `Glob` | policy / runbooks |
| `document_analysis` | a specific attached doc | `Read` | deep single-doc read |
| `synthesis` | merge findings, flag gaps | — (no tools) | owns the answer |

Each subagent is **its own context window and shares nothing** with the coordinator or its
peers. Every subtask prompt is therefore *self-contained*: it restates the full question,
the scope it owns, and the quality bar. Toolsets are kept tiny per role because selection
reliability degrades as tool count grows (see SA-13 / `tooling.py`).

`AgentSpec` is SDK-independent so the module imports with no SDK installed;
`build_agent_definitions()` projects specs into real `claude_agent_sdk.AgentDefinition`
objects lazily.

## Dynamic selection — not "always all four"

`select_subagents(query)` routes from the question to only the roles it needs. A purely
external question (`"latest news on our competitor"`) spawns `web_search` alone; a question
spanning internal docs *and* current news spawns both plus `synthesis` (someone must own
the merge). No signal → fall back to a single web search, so a question is always attempted.

## Decomposition: partition, goals not procedures

`decompose(query, roles)` gives each researcher role a **non-overlapping scope** and a
prompt that states a **GOAL + QUALITY CRITERIA**, never step-by-step instructions — the
subagent decides its own method. `synthesis` is a *merge* role, not a research slice, so it
gets no scope here; it consumes the others' findings in `run_research`.

### The too-narrow failure (reproduced and fixed)

`naive_decompose(query, n)` reproduces the classic mistake: chop the question into `n` tiny
same-role slivers. `is_too_narrow()` flags it (many subtasks pile onto one role). The
symptoms: subtasks overlap in role, no one owns synthesis, prompts are procedural
fragments, and gaps fall through the cracks. The fix is the partition-by-complementary-role
decomposition above — goals and criteria, not micro-procedures.

## Parallelism is the point

Independent subtasks are issued as `Task` calls **in a single response** so they run
concurrently. `latency_seconds(subtasks, mode=...)`:

- `parallel` → the slowest single subtask (`per_task`)
- `sequential` → the sum (`n * per_task`)

So three 2 s subtasks cost **2 s** in parallel vs **6 s** serial — the speedup is the
fan-out width. `run_research` spawns each round's subtasks with `asyncio.gather`.

## Iterative refinement loop

`run_research(query, *, spawn_fn, synthesize_fn, criteria, max_rounds)`:

1. `select_subagents` → `decompose`
2. spawn all subtasks concurrently (`spawn_fn`; the real one fans out parallel `Task` calls)
3. `synthesize_fn` merges the findings
4. `find_gaps(criteria, answer)` → any unmet criterion becomes a fresh, self-contained
   follow-up subtask; loop until criteria are met **or** `max_rounds` is hit

The round cap is a **logged safety net, not the primary stop condition** — the loop exits
early the moment the criteria are satisfied (agent-architecture.md: iteration cap is never
the primary terminator). `spawn_fn`/`synthesize_fn` are injected, so the whole loop is
tested offline with fakes.

## Structured context + provenance (SA-22)

Subagents return **structured `Finding` objects, not prose** (`src/research/schemas.py`), so
attribution survives the hop to synthesis. A `Finding` separates **content** (`claim`,
`evidence`) from **metadata** (`source`, `source_date`, `content_type`), plus a `topic`
(grouping key) and a comparable `value`. `finding_tool_def()` projects the model into a
`record_finding` tool `input_schema` — subagents emit findings by *calling* the tool (one
call per claim), so output is guaranteed-shaped and never loses its source.

`synthesize(findings)` (`src/research/synthesis.py`) groups by `topic` and classifies each
group, preserving claim→source mappings end-to-end:

| Status | Condition | Rendering |
|---|---|---|
| `established` | one value, ≥2 independent sources | type-appropriate + "corroborated by N sources" |
| `single` | one value, one source | type-appropriate + "not yet corroborated" |
| `temporal` | differing values, **each at a different date** | type-appropriate + "values differ over time" |
| `contested` | differing values at the **same date**, or an **undated** differing value | side-by-side, every value attributed |

The temporal-vs-contested split is why dates are required: a value that *changed over time*
is a time series, not a contradiction. An **undated** disagreement is treated conservatively
as contested — we never assume change we can't prove, and never arbitrarily collapse two
credible sources. Rendering is type-appropriate: `financial` → table, `news` → prose with
inline citations, `technical`/other → bulleted list. Every claim cites its source.

## How to run the tests

```bash
PYTHONPATH=src python -m pytest tests/test_orchestration.py tests/test_provenance.py -q
```
