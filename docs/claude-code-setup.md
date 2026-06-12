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

## 4. Verifying what loads — `/memory` vs. the `InstructionsLoaded` hook

### Documented behavior (official docs)
- **Trigger:** path-scoped rules load **when Claude *reads* a file matching the `paths:`
  glob** — a `Read` is enough; you do **not** need to edit the file. ("Path-scoped rules
  trigger when Claude reads files matching the pattern, not on every tool use.")
- **`@import` + startup files** load at session start. **Nested `CLAUDE.md`** (e.g.
  `tests/CLAUDE.md`) loads on-demand when Claude reads a file in that subtree.
- **`/memory` lists only what has *already* loaded this session** — it's a state display,
  not a predictor. So a rule shows up only *after* a matching file has been read.

### `/memory` proved unreliable here — use the hook
In testing, a successful `Read tests/test_loop.py` did **not** surface
`.claude/rules/testing.md` in `/memory`. Per the docs, the authoritative way to see what
loads (and *why*) is the **`InstructionsLoaded` hook**, which fires with a `load_reason`
of `session_start | include | nested_traversal | path_glob_match | compact`.

This repo ships that hook (`.claude/settings.json` → `.claude/hooks/log_instructions.py`),
which appends every load event to `.claude/instructions-loaded.log` (gitignored).

**Procedure (run at the repo root):**
1. Start a **fresh** `claude` session (hooks load at startup, so a new session is required
   after pulling these settings).
2. Open `.claude/instructions-loaded.log`. It should already contain `session_start` /
   `include` lines for `CLAUDE.md` and the three standards — that confirms the hook itself
   works. **If the log is empty, the `InstructionsLoaded` event isn't supported in your
   Claude Code version** (record that and rely on nested `CLAUDE.md` instead — see §5).
3. Ask Claude to `Read tests/test_loop.py`. Re-open the log → expect a line for
   `.claude/rules/testing.md` with `load_reason: path_glob_match`, and `tests/CLAUDE.md`
   with `nested_traversal`.
4. Ask Claude to `Read src/agent/tools.py` → expect `.claude/rules/mcp-conventions.md`
   with `path_glob_match`.

### Findings log
| Check | Expected | Observed | ✓/✗ |
|---|---|---|---|
| Startup loads project `CLAUDE.md` + 3 standards | `session_start`/`include` lines | _(fill from log)_ | |
| Reading `tests/test_loop.py` loads `testing.md` | `path_glob_match` | _(fill)_ | |
| Reading `tests/…` loads `tests/CLAUDE.md` | `nested_traversal` | _(fill)_ | |
| Reading `src/agent/tools.py` loads `mcp-conventions.md` | `path_glob_match` | _(fill)_ | |
| `/memory` lists the above after they load | listed | _(fill)_ | |

> Observed note (2026-06-12): `/memory` did **not** display `testing.md` after a confirmed
> `Read` of `tests/test_loop.py`. The hook log is the source of truth; complete the Observed
> column from `.claude/instructions-loaded.log`.

## 5. Precedence / risk notes
- When a directory `CLAUDE.md` and a path rule both match, both load; treat the
  directory file as scope and the rule as cross-cutting policy. If they conflict,
  the more specific (directory) wins — document any surprise here.
- Keep `CLAUDE.md` short. Bloated always-loaded memory costs context on every turn;
  push detail into `@import` modules and path-scoped rules that load on demand.
