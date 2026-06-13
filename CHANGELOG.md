# Changelog

All notable changes to ResolveDesk are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project tracks the Jira
[SUPPORT AGENT (SA)](https://projecttracking.atlassian.net/browse/SA) backlog rather than
semantic releases.

## Project status — 2026-06-13

**29 of 30 backlog stories Done · 274 tests passing (3 skipped, live-API only) · ruff clean.**
Every story shipped through the full SDLC: branch → offline tests → PR → independent CI review
(a second Claude instance) → fix findings → merge → Jira Done. SA-36 (timed mock exams) is held
**In Progress** — its materials are built, but the score trend and ≥80% bar are the candidate's
to record.

## [0.1.0] — 2026-06-13

### Agent core & policy
- **SA-8** — agentic loop: `stop_reason` reference loop (`agent/loop.py`) + production Agent SDK
  harness (`agent/sdk_agent.py`).
- **SA-9** — session resumption/forking: `--resume`, `fork_session`, and fresh-session-with-summary
  on stale context (`agent/sessions.py`).
- **SA-14** — programmatic prerequisite gate: verified customer before order actions
  (`agent/gates.py`).
- **SA-15** — Agent SDK hooks: PreToolUse refund-threshold interception + PostToolUse normalize
  (`agent/hooks.py`).
- **SA-16** — escalation criteria with few-shot examples + structured human-handoff payload
  (`agent/escalation.py`).

### MCP tools & resources
- **SA-10** — FastMCP backend + core tools (`mcp_server/`).
- **SA-11** — structured error envelopes (category, retryable, customer-safe message)
  (`mcp_server/errors.py`).
- **SA-12** — policy catalog exposed as an MCP resource (`mcp_server/resources.py`).
- **SA-13** — tool distribution + `tool_choice` strategies; role-scoped toolsets
  (`agent/tooling.py`).

### Document extraction
- **SA-17** — extraction schemas via `tool_use` with nullable fields (`extraction/schemas.py`).
- **SA-18** — validation-retry loop with semantic checks (`extraction/validate.py`, `retry.py`).
- **SA-19** — historical-backlog batch processing via the Message Batches API (`extraction/batch.py`).
- **SA-20** — field-level confidence scoring + calibrated human-review routing
  (`extraction/confidence.py`, `review/router.py`).

### Multi-agent research orchestration (Epic SA-5 — complete)
- **SA-21** — coordinator with parallel subagent spawning via the `Task` tool; dynamic selection,
  scope-partitioning decomposition, refinement loop (`research/agents.py`, `coordinator.py`).
- **SA-22** — structured findings with provenance preserved through synthesis; conflicts shown
  side-by-side, temporal change ≠ contradiction (`research/schemas.py`, `synthesis.py`).
- **SA-23** — structured subagent error propagation + coverage annotation; workflow never dies on
  one failure (`research/errors.py`).
- **SA-24** — crash recovery via an atomically-persisted manifest + scratchpads/phase summaries
  (`research/manifest.py`, `state.py`).

### Long-context support (Epic SA-7 — complete)
- **SA-28** — persistent case-facts context layer + tool-output trimming; exact figures survive a
  20+ turn conversation (`agent/case_facts.py`, `trimming.py`).
- **SA-29** — multi-issue decomposition with parallel investigation + dependency sequencing
  (`agent/decompose.py`).
- **SA-30** — evaluation harness: 30-scenario suite, FCR + both-direction escalation metrics,
  independent rubric judge, JSON/markdown report (`eval/`).

### Claude Code config & CI self-review
- **SA-25** — `CLAUDE.md` hierarchy + path-scoped rules.
- **SA-26** — project slash commands + forked skills.
- **SA-27** — independent CI PR review via `claude -p` (`.github/workflows/claude-review.yml`,
  `ci/run_review.py`); gated by `ENABLE_CLAUDE_REVIEW`, `REVIEW_MODEL` defaults to sonnet.
- **SA-34** — plan-mode decision drills.
- **SA-38** — CI review auth switched to the Max-subscription OAuth token.
- **SA-35** — multi-pass independent review pipeline: per-file + cross-file integration passes,
  confidence-routed (`review/pipeline.py`, `passes.py`).

### Dev-productivity & exam-prep drills
- **SA-32** — built-in tool-selection drills (Grep/Glob/Edit/Read+Write) — `docs/drills/builtin-tools.md`.
- **SA-33** — context-efficient large-codebase investigation (Explore subagent, session strategy,
  plan vs direct) — `docs/drills/context-exploration.md`.
- **SA-37** — anti-pattern recognition drills + meta-principles cheat sheet — `docs/exam/anti-patterns.md`.

### In progress
- **SA-36** — Week-4 timed mock-exam bank, answer keys, score tracker, and miss→re-drill map
  (`docs/exam/mock-exams.md`). Materials complete; awaiting the candidate's timed sittings and
  recorded score trend (final mock ≥ 80%).

[0.1.0]: https://github.com/dharmendra-verma/Support-Agent
