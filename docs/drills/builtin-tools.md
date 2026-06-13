# Built-in tool-selection drills (SA-32)

Hands-on practice for **CCA-F D2 TS 2.5** — judgment about Claude Code's built-in tools
(Grep vs Glob, Edit failure modes, exploration order). Every drill below was **run against this
ResolveDesk repo**; the numbers are the actual results, not hypotheticals. Each is timed to a
single tool call or two — the point is reflexes, not reading docs.

The one-line decision rule the drills build toward:

> **Content search → Grep. Path/name match → Glob. Trace a flow → Read (incrementally). Change
> a known span → Edit. Anchor not unique → expand it, `replace_all`, or Read+Write.**

---

## Drill 1 — Find all callers of a function → **Grep**

**Task:** where is `extract_facts` used before I change its signature?

**Tool:** `Grep(pattern="extract_facts", output_mode="content", -n=true)`

**Result (actual):** 8 matches across 3 files. The one that matters for a signature change is the
production call site `src/agent/decompose.py:101` (`facts=extract_facts(clause)`); the definition
is `src/agent/case_facts.py:93`; the rest are tests.

**Why Grep, not Glob or Read:** the question is about *content* (a symbol) whose locations are
unknown. Glob matches paths, not code; reading files one-by-one to look for callers is O(repo).
Grep answers it in one pass and gives `file:line` you can jump to. Use `-A`/`-C` for context, or
`output_mode="count"` when you only need "how many / which files".

---

## Drill 2 — Find files by pattern → **Glob**

**Task:** list every test module.

**Tool:** `Glob(pattern="tests/**/test_*.py")`

**Result (actual):** 22 files (`test_sdk_agent.py`, `test_loop.py`, … `test_eval_harness.py`).

**Why Glob, not Grep:** the selection criterion is the *path/name shape*, not file contents. Grep
would need a content pattern and would still scan bodies; Glob matches the directory structure
directly and returns paths sorted by mtime (handy for "what changed recently"). Rule of thumb: if
you can express the target as a shell glob (`**/*.tsx`, `src/**/__init__.py`), reach for Glob.

---

## Drill 3 — Targeted modification → **Edit**

**Task:** raise the auto-approval limit constant.

**Tool:** `Edit(file_path="mcp_server/backend.py", old_string="REFUND_AUTO_APPROVE_LIMIT = 500.0", …)`

**Result (actual):** the bare token `REFUND_AUTO_APPROVE_LIMIT` appears **twice** — the definition
at `backend.py:14` and a usage at `:62` (`auto = amount <= REFUND_AUTO_APPROVE_LIMIT`). Anchoring
on the full assignment `REFUND_AUTO_APPROVE_LIMIT = 500.0` is **unique**, so the Edit lands in one
shot and can't accidentally touch the comparison on line 62.

**Why Edit, not Read+Write:** the change is a small, well-located span. Edit is surgical (no risk
of clobbering the rest of the file) and doesn't spend tokens re-emitting the whole module. The
craft is choosing an `old_string` that is unique *and* minimal — include just enough (`= 500.0`)
to disambiguate from the usage site.

---

## Drill 4 — Edit anchor is non-unique → **expand it, `replace_all`, or Read+Write**

**Task:** change the queue-path handling in `src/review/router.py`.

**Collision (actual):** `p = Path(path)` appears at **two** lines — `router.py:45` (in `enqueue`)
and `:52` (in `read_queue`). A bare Edit on `old_string="p = Path(path)"` fails: *not unique*.
(Same shape inside `case_facts.py`, where `facts._add(...)` recurs 6×.)

**Three correct recoveries, by intent:**

1. **Change one site →** expand the anchor with surrounding unique context, e.g. include the line
   above/below so the match is unambiguous (`old_string` spanning the `def read_queue` body).
2. **Change every site identically →** `Edit(..., replace_all=true)` — deliberate, all-or-nothing.
3. **Structural rewrite (many edits, moved code) →** Read the file, then Write it back wholesale.
   Read+Write is the fallback when the change is too interleaved for clean anchors — you accept
   the token cost of re-emitting the file in exchange for correctness.

**Why this matters:** Edit's uniqueness requirement is a *safety feature*, not an obstacle —
it refuses to guess which `p = Path(path)` you meant. The failure mode to avoid is forcing a
too-short anchor and silently editing the wrong occurrence.

---

## Drill 5 — Incremental exploration (NOT read-everything)

**Task:** understand how the SDK agent runs, starting cold.

**Path taken:**
1. Entry point: `Read(src/agent/sdk_agent.py)` — **140 lines**.
2. `Grep(^(from|import), src/agent/sdk_agent.py)` → it imports only stdlib (`dataclasses`,
   `typing`) and **lazy-imports `claude_agent_sdk` inside the functions** (lines 62, 127). So there
   is no heavy import graph to chase — the dependency is deferred by design (python-style.md).
3. Read just the two functions that matter (`build_options`, `run_support_agent`) — already in
   those 140 lines.

**Token comparison (actual):** reading the whole `src/` tree as a baseline is **30 files /
3,104 lines**. The incremental path read **~140 lines** (one file) plus two cheap Grep results —
on the order of a **~90%+ reduction** versus read-everything, and it answered the question.

**Rule:** start at the entry point, Grep for the edges (imports, call sites), and Read only the
nodes on the path. Reading the repo upfront burns context on files you'll never reference.

---

## Drill 6 — Wrapper-module tracing (enumerate exports, then Grep each)

**Task:** `src/agent/tooling.py` wraps the MCP server and adds scoped tools — what does it export,
and who consumes each?

**Step 1 — enumerate exports** (`grep -E "^(def |class |[A-Z_]+ =)"`): `auto`, `any_tool`,
`force`, `none`, `CHECK_REFUND_STATUS_SCHEMA`, `check_refund_status`, `ALL_SCHEMAS`, `HANDLERS`,
`ROLE_TOOLS`, `register_extra_tools`, `tools_for`, `refund_workflow_steps`.

**Step 2 — Grep each across the repo.** Tracing the public trio
`tools_for|refund_workflow_steps|check_refund_status` →  **32 matches across 5 files**:
`mcp_server/server.py` (wires `register_extra_tools`/`check_refund_status`),
`tests/test_tool_choice.py` (heaviest consumer, 14), `docs/tool-distribution.md` (4),
`eval/scenarios/__init__.py` (1), and the definitions in `tooling.py` itself (12).

**Why this two-step beats reading the module:** a wrapper's value is in *who depends on it*.
Enumerating the surface first, then Grepping each name, maps the blast radius of a change without
reading every consumer — and immediately shows that `test_tool_choice.py` is the contract test to
run after touching this module.

---

## Decision rules (the cheat sheet)

| Need | Tool | Tell |
|---|---|---|
| Find a symbol / string / callers | **Grep** | criterion is *content*; locations unknown |
| Find files by name/path shape | **Glob** | criterion is a *path glob* (`**/test_*.py`) |
| Understand a flow | **Read** (incremental) | start at entry point; Read only nodes on the path |
| Change a known, localized span | **Edit** | pick a *unique, minimal* anchor |
| Anchor repeats in the file | **Edit (expanded / `replace_all`)** | add context, or change all deliberately |
| Interleaved / structural rewrite | **Read + Write** | accept re-emit cost for correctness |
| Map a wrapper's blast radius | **Grep exports** | enumerate names, Grep each |

**Anti-patterns** (each maps to a wrong-answer choice on a TS 2.5 question):
- Glob to find *code* (it matches paths, not contents) — use Grep.
- Reading the whole repo "to be safe" before answering — Grep/Glob to locate, Read to confirm.
- Forcing a non-unique Edit anchor — Edit refuses for a reason; expand it or `replace_all`.
- Read+Write for a one-line change — wasteful; that's Edit's job.
