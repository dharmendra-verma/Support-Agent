# ResolveDesk

Autonomous customer-support resolution agent, built as a **CCA-F (Claude Certified Architect –
Foundations) practice application**. The agent resolves support requests end-to-end — verifying
customers, looking up orders, processing refunds within policy, extracting data from documents,
researching across sources, and escalating to humans when it should — and every subsystem is a
worked example of a CCA-F task statement.

Jira: [SUPPORT AGENT (SA)](https://projecttracking.atlassian.net/browse/SA) ·
Code: [github.com/dharmendra-verma/Support-Agent](https://github.com/dharmendra-verma/Support-Agent)

## Status

**29 of 30 backlog stories Done** · **274 tests passing** (3 skipped, live-API only) · ruff clean.

| Epic / group | Stories | State |
|---|---|---|
| Agent core & policy (loop, gates, hooks, escalation, sessions) | SA-8, 9, 14, 15, 16 | ✅ |
| MCP tools & resources (backend, tools, errors, resources, distribution) | SA-10, 11, 12, 13 | ✅ |
| Document extraction (schema → validate/retry → batch → confidence/routing) | SA-17, 18, 19, 20 | ✅ |
| **Multi-agent research orchestration** (SA-5) | SA-21, 22, 23, 24 | ✅ epic complete |
| **Long-context support** (SA-7) | SA-28, 29, 30 | ✅ epic complete |
| Claude Code config & CI self-review | SA-25, 26, 27, 34, 38 | ✅ |
| Dev-productivity & exam-prep drills | SA-32, 33, 35, 37 | ✅ |
| Week-4 timed mock exams | SA-36 | 🟡 materials ready; awaiting candidate's mock sittings |

## Architecture rule (the two-path principle)

- **Agentic work → Claude Agent SDK.** Production agent loops run through `claude-agent-sdk`
  (`query`/`ClaudeSDKClient`, in-process `@tool` + `create_sdk_mcp_server`). Termination is driven
  by `stop_reason`/`ResultMessage`, never by parsing the model's prose.
- **Non-agentic work → direct Anthropic Messages API.** Single-shot classify/extract/review calls
  (and the bulk Message Batches pipeline) use the `anthropic` SDK directly. `src/agent/loop.py` is
  the one sanctioned hand-rolled loop, kept as a stop_reason reference implementation.

Policy invariants are enforced **programmatically** (deterministic gates/hooks), not by prompting.

## Stack

Python 3.11+ · `claude-agent-sdk` · `anthropic` (Messages + Batches API) · `fastmcp` / `mcp` ·
`pydantic` · `pytest` + `ruff`.

## Layout

```
src/
  agent/        loop.py (ref stop_reason loop) · sdk_agent.py (SDK harness) · gates.py ·
                hooks.py (refund threshold) · escalation.py · sessions.py (resume/fork/fresh) ·
                tooling.py (tool_choice + role-scoped tools) · case_facts.py · trimming.py · decompose.py
  extraction/   schemas.py · extractor.py · validate.py · retry.py · batch.py · confidence.py
  research/     agents.py · coordinator.py · schemas.py · synthesis.py · errors.py · manifest.py · state.py
  review/       router.py · passes.py · pipeline.py (multi-pass independent review)
mcp_server/     backend.py · server.py (FastMCP) · errors.py (structured envelopes) · resources.py
eval/           scenarios/ · harness.py · judge.py · report.py   (FCR + escalation + quality metrics)
ci/             run_review.py · post_comments.py   (independent CI reviewer, `claude -p`)
tests/          one module per subsystem; offline & deterministic (injected fakes)
docs/           per-subsystem write-ups + drills/ + exam/
```

## Setup

```bash
python -m venv .venv && . .venv/Scripts/activate   # Windows
pip install -e ".[dev]"
cp .env.example .env   # add ANTHROPIC_API_KEY (only for the live-skipped tests)
pytest                 # offline: no network, no API key required
ruff check src tests
```

## Quality gates (Definition of Done)

Every story: branch `feature/SA-<n>-<slug>` → tests added (offline, deterministic) → PR to `main`
→ **independent CI review** (a second Claude instance, no generator context — `.github/workflows/
claude-review.yml`, gated by the `ENABLE_CLAUDE_REVIEW` repo variable, `REVIEW_MODEL` defaults to
sonnet) → fix findings → merge → Jira transitioned to Done. The CI reviewer has caught and forced
fixes for dozens of real defects across the backlog; see `docs/multi-pass-review.md`.

## Docs

Per-subsystem write-ups live in `docs/` — e.g. `research-orchestration.md`, `long-context.md`,
`multi-issue.md`, `eval-harness.md`, `multi-pass-review.md`, `policy-gates.md`, `hooks-policy.md`,
`batch-strategy.md`, `mcp-tools.md`, `ci-review.md`, `claude-code-setup.md`. Exam-prep drills and
mock exams are under `docs/drills/` and `docs/exam/`.

## Conventions

- Branches: `feature/SA-<n>-<slug>`; conventional commits (`feat(SA-n):`, `fix(SA-n):`, …).
- Tests stay **offline and deterministic** — inject fakes; live model paths are `skipif` on `ANTHROPIC_API_KEY`.
- Lazy-import heavy SDKs so modules import without a key; one source of truth per tool schema.
