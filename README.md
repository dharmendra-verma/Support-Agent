# ResolveDesk

Autonomous customer-support resolution agent. The engine repeatedly calls backend
tools (via the Anthropic Messages API) until a support request is resolved.

CCA-F practice application — Jira project [SUPPORT AGENT (SA)](https://projecttracking.atlassian.net/browse/SA).

## Stack
- Python 3.11+
- `anthropic` (Messages API), `pydantic`
- `pytest` for tests

## Layout
```
src/agent/
  client.py   # thin Anthropic Messages API wrapper + usage accounting
  loop.py     # agentic loop: dispatch on stop_reason, accumulate context
  tools.py    # tool registry pattern (name -> schema + handler)
tests/
  test_loop.py
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
