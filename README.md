# ResolveDesk

Autonomous customer-support resolution agent. The engine repeatedly calls backend
tools (via the Anthropic Messages API) until a support request is resolved.

CCA-F practice application — Jira project [SUPPORT AGENT (SA)](https://projecttracking.atlassian.net/browse/SA).

## Stack
- Python 3.11+
- `claude-agent-sdk` — agentic harness (owns the loop, in-process MCP tools)
- `anthropic` (Messages API) — direct/single-shot calls + the reference loop
- `pydantic`; `pytest` for tests

**Architecture rule:** agentic work runs through the Claude Agent SDK; the direct
Claude API is used wherever a call isn't agentic (and for the reference loop below).

## Layout
```
src/agent/
  sdk_agent.py  # PRODUCTION harness on the Claude Agent SDK (query/ClaudeSDKClient)
  loop.py       # direct Messages-API reference loop: raw stop_reason control flow
  client.py     # thin anthropic wrapper + cumulative usage (used by the ref loop)
  tools.py      # tool registry; one handler -> ref loop AND SDK @tool server
tests/
  test_sdk_agent.py  # asserts on what the SDK surfaces (text, usage, turns)
  test_loop.py       # raw loop termination paths
```

## Setup
```bash
python -m venv .venv && . .venv/Scripts/activate   # Windows
pip install -e ".[dev]"
cp .env.example .env   # add ANTHROPIC_API_KEY
pytest
```

## Conventions
- Branches: `feature/SA-<n>-<slug>`
- Every story adds tests; all must pass before Done.
