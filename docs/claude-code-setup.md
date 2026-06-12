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

This repo ships the hook **script** (`.claude/hooks/log_instructions.py`), which appends
every load event to `.claude/instructions-loaded.log` (gitignored). The hook is **opt-in
and personal** — it is *not* registered in committed config, so it never runs for the team
by default. To enable it for yourself, add this block to your **`.claude/settings.local.json`**
(personal, gitignored):

```json
{
  "hooks": {
    "InstructionsLoaded": [
      { "hooks": [ { "type": "command", "command": "python .claude/hooks/log_instructions.py" } ] }
    ]
  }
}
```

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

### Findings log (observed 2026-06-12, Claude Code on Windows)
| Check | Expected | Observed | ✓/✗ |
|---|---|---|---|
| Startup loads project `CLAUDE.md` + 3 `@import` standards | `session_start`/`include` lines | 4 entries logged (`CLAUDE.md` + python-style + agent-architecture + git-workflow) | ✅ |
| `/memory` lists project + standards | listed | shown | ✅ |
| Reading `tests/test_loop.py` loads `testing.md` | `path_glob_match` | no new hook entry; not shown in `/memory` | ⚠️ unconfirmed |
| Reading/under `tests/` loads `tests/CLAUDE.md` | `nested_traversal` | no new hook entry | ⚠️ unconfirmed |
| Editing `tests/test_loop.py` loads scoped memory | a load event | no new hook entry | ⚠️ unconfirmed |
| Reading `src/agent/tools.py` loads `mcp-conventions.md` | `path_glob_match` | not exercised | — |

**Finding.** Levels 1–2 of the hierarchy (project `CLAUDE.md` + `@import` composition) are
**proven** to load — confirmed by both `/memory` and the `InstructionsLoaded` hook log.
Levels 3–4 (directory override `tests/CLAUDE.md`, path-scoped `.claude/rules/*.md`) are
present and **spec-correct per the official docs**, but their **scoped loading was not
observed** in this session via `/memory` or the hook, on either read or edit of a matching
file.

**Caveat on the negative result.** The level-3/4 check is **not conclusive**: hooks load at
**session start**, and the test was run in a session that likely began before
`.claude/settings.json` was present (the hook log stayed frozen at a prior session's
entries, indicating the hook wasn't active in the test session). A clean confirmation needs
a **fresh session started after** the settings land, with the log cleared and a matching
file read as the first action (the procedure in this section). Treat levels 3–4 as
"configured correctly, scoped-load unconfirmed on this build" until that re-run is done.

**Practical guidance.** Where guaranteed loading matters, prefer the better-supported
mechanisms (project `CLAUDE.md` + `@import`, and nested `CLAUDE.md`) over relying on
`.claude/rules/` path globs; keep the path rules as progressive enhancement and re-verify
on the team's target Claude Code version with the hook log.

## 5. Precedence / risk notes
- When a directory `CLAUDE.md` and a path rule both match, both load; treat the
  directory file as scope and the rule as cross-cutting policy. If they conflict,
  the more specific (directory) wins — document any surprise here.
- Keep `CLAUDE.md` short. Bloated always-loaded memory costs context on every turn;
  push detail into `@import` modules and path-scoped rules that load on demand.

## 6. CI auth: subscription OAuth token (SA-38)

The CI reviewer (`.github/workflows/claude-review.yml`) authenticates `claude -p` with a
**Max/Pro subscription OAuth token** instead of `ANTHROPIC_API_KEY`, so review runs draw
from the subscription quota at **zero marginal API cost** (no per-token Console billing).

### Generate & store (one time)
```bash
claude setup-token        # interactive; requires a logged-in Pro/Max session locally
# copy the printed token, then store it as a repo secret (never commit it):
gh secret set CLAUDE_CODE_OAUTH_TOKEN --repo <owner>/<repo>   # paste at the prompt
```
The workflow reads it via `CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}`;
the CLI resolves the token from that env var automatically.

### Lifecycle
- **Expiry / invalidation:** the token is tied to your Claude session. It is **invalidated
  if you log out** (`claude` logout) and **expires periodically**. When it lapses, CI fails
  at the review step with an auth error — it does not silently pass.
- **Regenerate:** re-run `claude setup-token` and update the secret:
  ```bash
  gh secret set CLAUDE_CODE_OAUTH_TOKEN --repo <owner>/<repo>
  ```
- **Rotate:** the same command overwrites the existing secret; no workflow change needed.

### Tradeoff (read before enabling on a busy repo)
CI now shares the **Max plan's rolling usage limits** with your interactive Claude Code
sessions — heavy PR churn can throttle both. If reviews shouldn't ride a personal
subscription (shared/team CI), switch back to the **`ANTHROPIC_API_KEY` fallback**
(uncomment its line in the workflow, comment out the OAuth line) — that bills per-token to
the Console account but isolates CI from your subscription quota.
