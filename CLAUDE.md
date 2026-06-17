# ResolveDesk — Claude Code project guide

Autonomous customer-support resolution agent (CCA-F practice app). This file is the
**project-level** memory: committed to git, loaded for every developer on every session.
Keep it lean — detailed standards live in the imported modules below.

## What this is
- Python 3.11+ agent. **Claude Agent SDK owns the agentic loop**; the direct Claude
  Messages API (`anthropic`) is used for non-agentic/single-shot calls and the
  `loop.py` stop_reason reference implementation.
- Jira project [SUPPORT AGENT (SA)](https://projecttracking.atlassian.net/browse/SA);
  code on [GitHub](https://github.com/dharmendra-verma/Support-Agent).
- Architecture: see [`docs/architecture-sa39.md`](docs/architecture-sa39.md) for the live
  research-agent flow (CLI → `run_research` coordinator → parallel role-scoped subagents via the
  SDK `Task` tool → provenance-preserving synthesis), as Mermaid diagrams.

## Standards (composed via @import — edit the module, not this file)
@.claude/standards/python-style.md
@.claude/standards/agent-architecture.md
@.claude/standards/git-workflow.md
@.claude/standards/review-criteria.md

## Memory hierarchy (precedence: most-specific wins)
1. **Enterprise/user** (`~/.claude/CLAUDE.md`) — personal, **NOT shared via git**.
2. **Project** (this file) — team conventions, committed.
3. **Directory** (`<pkg>/CLAUDE.md`) — overrides for that subtree (e.g. `tests/CLAUDE.md`).
4. **Path-scoped rules** (`.claude/rules/*.md`) — load only when editing files matching
   their `paths:` globs.

See `docs/claude-code-setup.md` for the full setup, precedence notes, and `/memory`
verification findings.

## Quick commands
- Install: `pip install -e ".[dev]"`
- Test: `pytest` (must stay green and offline — no network, no API key)
- Lint: `ruff check src tests`
