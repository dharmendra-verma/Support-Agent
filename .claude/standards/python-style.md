# Python style (universal)

- Target **Python 3.11+**; `from __future__ import annotations` at the top of modules
  that use forward refs.
- Type-hint all public functions. Prefer `dataclass` for value objects.
- Line length **100** (ruff-enforced). Run `ruff check src tests` before committing.
- Lazy-import heavy / network-bound SDKs (`anthropic`, `claude_agent_sdk`) inside the
  function that needs them, so importing a module never requires an API key.
- Errors: raise typed exceptions (e.g. `MaxTokensError`, `UnknownToolError`); never
  swallow a programming error as data. Surface genuine tool *runtime* failures back to
  the model, but fail fast on config/registry drift.
