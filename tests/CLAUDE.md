# tests/ — directory-level override

This file loads **in addition to** the project `CLAUDE.md` whenever you work under
`tests/`, and overrides it where they disagree (most-specific wins).

- Default to writing tests, not production code, in this subtree.
- Mirror the module under test: `src/agent/loop.py` → `tests/test_loop.py`.
- Reuse the existing fakes (`FakeClient`, fake `runner`, `Block`/`Resp` doubles)
  before inventing new ones.
- This directory is `pytest`-discovered via `pyproject.toml` (`pythonpath=["src"]`),
  so import the package as `from agent.… import …`, not via relative paths.

(See `.claude/rules/testing.md` for the path-scoped testing rules that also apply here.)
