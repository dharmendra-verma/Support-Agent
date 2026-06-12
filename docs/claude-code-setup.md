# Claude Code setup — memory hierarchy & path-scoped rules (SA-25)

How team conventions reach every developer automatically, and how per-file-type rules
apply across directories. Open Claude Code at the repo root to pick all of this up.

## 1. Memory hierarchy & precedence

Claude Code composes memory from several sources. **More specific wins** on conflict;
non-conflicting guidance is additive.

| Level | File | Scope | Shared via git? |
|---|---|---|---|
| User | `~/.claude/CLAUDE.md` | every project for *you* | ❌ **No** — personal only |
| Project | `./CLAUDE.md` | this repo, all devs | ✅ Yes (committed) |
| Directory | `<pkg>/CLAUDE.md` (e.g. `tests/CLAUDE.md`) | that subtree | ✅ Yes |
| Path rules | `.claude/rules/*.md` with `paths:` globs | files matching the glob | ✅ Yes |

### The user-level trap
Putting team conventions in `~/.claude/CLAUDE.md` "works on your machine" but is **never
shared** — teammates and CI don't get it, so behavior silently diverges. Rule of thumb:
**personal preferences → user file; anything the team/CI must honor → project `CLAUDE.md`
or `.claude/`** (committed).

Example of what belongs *only* in the user file (do **not** commit):
```md
# ~/.claude/CLAUDE.md  (personal, not in git)
- Use my scratch dir ~/tmp for throwaway experiments.
- Prefer verbose explanations when I'm debugging.
```

## 2. Modular composition with `@import`

The project `CLAUDE.md` stays lean and pulls in standards modules:
```md
@.claude/standards/python-style.md
@.claude/standards/agent-architecture.md
@.claude/standards/git-workflow.md
```
Each `@path` line inlines that file's content. Edit the **module**, not `CLAUDE.md`, so
standards stay single-source and reviewable in isolation.

## 3. Path-scoped rules (`.claude/rules/`)

Directory-bound `CLAUDE.md` files can't express "all test files everywhere", because a
file type spans directories. Path rules solve this with YAML frontmatter globs:

- `.claude/rules/testing.md` → `paths: ["**/test_*.py", "tests/**"]`
- `.claude/rules/mcp-conventions.md` → `paths: ["mcp_server/**/*", "src/agent/tools.py"]`

A rule loads **only** when the files you're editing match its globs — so MCP conventions
don't clutter context while you edit the loop, and vice versa.

## 4. Verifying with `/memory`

Run this in an **interactive Claude Code session opened at the repo root**:

1. `/memory` — lists every loaded memory file and its level. Expect: project `CLAUDE.md`
   plus the three `@import`ed standards modules.
2. Open a test file (e.g. `tests/test_loop.py`) and re-check `/memory` →
   `.claude/rules/testing.md` should now be listed; `mcp-conventions.md` should **not**.
3. Open `src/agent/tools.py` → `mcp-conventions.md` loads; `testing.md` drops off.
4. Work under `tests/` → `tests/CLAUDE.md` (directory override) is present alongside the
   project file.

### Findings log
Record observed behavior here when the live check is run (template):

| Check | Expected | Observed | ✓/✗ |
|---|---|---|---|
| Base session loads project + 3 standards | yes | _(pending interactive run)_ | |
| Editing `test_*.py` loads `testing.md` only | yes | _(pending)_ | |
| Editing `tools.py` loads `mcp-conventions.md` only | yes | _(pending)_ | |
| `tests/CLAUDE.md` overrides project under `tests/` | yes | _(pending)_ | |

> Note: the table is pre-filled with the documented hierarchy behavior; the **Observed**
> column must be completed from an actual `/memory` run before this story's AC is signed off.

## 5. Precedence / risk notes
- When a directory `CLAUDE.md` and a path rule both match, both load; treat the
  directory file as scope and the rule as cross-cutting policy. If they conflict,
  the more specific (directory) wins — document any surprise here.
- Keep `CLAUDE.md` short. Bloated always-loaded memory costs context on every turn;
  push detail into `@import` modules and path-scoped rules that load on demand.
