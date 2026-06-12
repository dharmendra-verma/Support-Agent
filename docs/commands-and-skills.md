# Project commands & skills (SA-26)

Recurring workflows get one-command invocation for everyone, and verbose work is kept
out of the main conversation. In current Claude Code, **commands and skills are the same
mechanism** (a markdown file with frontmatter); a skill is just a command in its own
directory that can ship supporting files and run in a forked context.

## `/review` — project slash command
`.claude/commands/review.md` → invoked as **`/review [base-branch]`**. Project-scoped and
committed, so every developer gets the same team review checklist. It applies the shared
criteria in `.claude/standards/review-criteria.md` (the same report-vs-skip rules the CI
reviewer uses), keeping human and automated review consistent.

Frontmatter used: `description`, `argument-hint`, `allowed-tools` (note: **hyphens**, not
underscores). Arguments are referenced with `$ARGUMENTS`.

### Personal (user-scoped) variant — demonstrates scoping
A personal command lives in **`~/.claude/commands/`** and is **NOT shared via git** — it's
yours alone, exactly like the user-level `CLAUDE.md` trap in `docs/claude-code-setup.md`.
Use a **distinct name** to avoid colliding with the project `/review`. Example you can drop
in `~/.claude/commands/review-fast.md`:
```md
---
description: My personal quick scan — just bugs, no checklist ceremony.
argument-hint: [base-branch]
allowed-tools: Bash(git diff:*)
---
Diff against `$ARGUMENTS` (default `main`) and list only likely bugs, one line each.
```
This is `/review-fast` for you only; teammates and CI never see it.

## `transcript-analysis` — forked skill
`.claude/skills/transcript-analysis/SKILL.md` → **`/transcript-analysis [path-or-glob]`**.
Three behaviors that matter (and how to verify each):

| Frontmatter | Purpose | How to verify |
|---|---|---|
| `context: fork` | runs in an isolated subagent → verbose reading leaves **no residue** in the main chat | run it on a transcript; only the summary returns, not the raw file dump |
| `allowed-tools: Read, Grep, Glob` | read-only; **blocked tools are refused** | ask it to edit/write a file → it declines (no `Write`/`Edit`/`Bash` available) |
| `argument-hint: [transcript-path-or-glob]` | prompts for the parameter in the `/` menu | type `/transcript-analysis` and see the hint |

## Decision note — skills/commands vs CLAUDE.md
Both deliver guidance, but they load very differently. Pick by **when** the guidance is needed.

| | `CLAUDE.md` (+ `@import`) | Skill / command |
|---|---|---|
| **Loading** | **Always** — injected into context every session/turn | **On-demand** — only when invoked (or auto-picked by `description`) |
| **Context cost** | Paid on every turn → keep it lean | Zero until used |
| **Best for** | Standards that should shape *all* work (style, architecture, review criteria) | Discrete, occasional **procedures** (run the checklist, analyze a transcript) |
| **Isolation** | None — shares the main context | `context: fork` runs in a subagent → no residue |
| **Tool limits** | n/a | `allowed-tools` restricts what it may do |

**Rule of thumb:** always-true conventions → `CLAUDE.md`; a procedure you run *sometimes*,
especially if it's verbose or should be sandboxed → a skill/command. That's why the review
*criteria* live in `CLAUDE.md` (every change should honor them) while the review *procedure*
and transcript analysis are commands/skills (run only when you ask).
