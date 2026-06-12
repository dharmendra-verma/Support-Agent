---
name: transcript-analysis
description: Analyze a ResolveDesk agent transcript (loop shape, tool calls, token usage, anti-patterns) and return a compact summary. Use when reviewing how an agent run behaved.
argument-hint: [transcript-path-or-glob]
context: fork
allowed-tools: Read, Grep, Glob
---

Analyze the agent transcript at `$ARGUMENTS` (a `.jsonl` / log path or glob).

This skill runs in a **forked** context (`context: fork`): do all the verbose reading
here and return ONLY the summary to the main conversation — no residue.

Report, concisely:
1. **Loop shape** — number of turns and the `stop_reason` / `ResultMessage` that ended it.
2. **Tool usage** — which tools were called, how often, and any errors or retries.
3. **Token usage** — cumulative input/output tokens if present.
4. **Anti-patterns** — prose-based stops, iteration-cap trips, or duplicated work.
5. **Verdict** — one line, plus the single highest-value improvement.

You have **read-only** tools by design (`Read`, `Grep`, `Glob`). Do not attempt to modify
files; if a task seems to need `Write`/`Edit`/`Bash`, report that instead of doing it.
