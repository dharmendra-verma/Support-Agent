# SA-39 — Live research agent architecture

How a research question flows from the command line through the deterministic coordinator,
fans out to **role-scoped subagents running in parallel via the Agent SDK**, captures
structured findings, and is synthesised into one provenance-preserving answer.

Three views: (1) end-to-end control flow, (2) what one `spawn_fn` does (the agentic core),
(3) a dynamic sequence of one refinement round.

---

## 1. End-to-end control flow

The CLI is a thin blocking shell; **`run_research` owns orchestration** (unchanged, DI'd); the
real SDK adapters live in `runner.py`. Parallelism is the `asyncio.gather` fan-out; the
refinement loop is bounded by `max_rounds` (a logged safety net, not the primary stop).

```mermaid
flowchart TD
    User([User]) -->|"run_research 'question' --criteria … --max-rounds N"| CLI

    subgraph CLILayer["CLI shell — scripts/run_research.py"]
        CLI["main(argv)"] --> Parse["argparse + _parse_criteria"]
        Parse --> Gate{"spawn_fn source?"}
        Gate -->|"--dry-run"| Dry["dry_run_spawn_fn<br/>(offline fake)"]
        Gate -->|"ANTHROPIC_API_KEY set"| Live["make_spawn_fn<br/>(live SDK)"]
        Gate -->|"no key & not dry-run"| Refuse["stderr msg → exit 2"]
        Synth0["make_synthesize_fn<br/>(deterministic, offline)"]
    end

    Dry --> Run
    Live --> Run
    Synth0 --> Run

    subgraph Core["Coordinator core — research/coordinator.py · run_research (untouched, DI)"]
        Run["run_research"] --> Select["select_subagents(query)<br/>→ roles"]
        Select --> Decomp["decompose(query, roles)<br/>→ non-overlapping Subtasks"]
        Decomp --> Loop{{"refinement loop (≤ max_rounds)"}}
        Loop --> Fan["asyncio.gather(spawn_fn(st) …)<br/><b>PARALLEL fan-out</b>"]
        Fan --> Collect["findings dict<br/>'role:scope' → JSON blob"]
        Collect --> SynthCall["synthesize_fn(findings)"]
        SynthCall --> Gaps["find_gaps(criteria, answer)"]
        Gaps -->|"gaps remain & rounds left"| Refine["build gap subtasks"] --> Loop
        Gaps -->|"no gaps OR cap hit"| Result["ResearchResult<br/>(answer, rounds, gaps)"]
    end

    Result --> Format["format_result()<br/>text or --json"]
    Format --> Out([stdout])

    SynthCall -.->|"calls"| SynthMod
    Fan -.->|"each call"| SpawnNote["one role-scoped subagent<br/>(see view 2)"]

    subgraph SynthMod["research/synthesis.py"]
        SY["synthesize(findings)"] --> GBT["group_by_topic → classify<br/>established / single / temporal / contested"]
        GBT --> MD["to_markdown()<br/>claim→source, conflicts side-by-side"]
    end
```

---

## 2. Inside one `spawn_fn` — the agentic core (live path)

Each `spawn(subtask)` launches **one** role-scoped subagent through the SDK `Task` tool. The
subagent inherits no coordinator context (the full `Subtask.prompt` is passed in) and is offered
only its role tools **plus** the in-process `record_finding` tool. Findings are captured
**structurally** (one `record_finding` call per claim), never by parsing prose. A per-subtask
`asyncio.wait_for` timeout guarantees a hung subagent can never hang the blocking CLI.

```mermaid
flowchart TD
    subgraph Spawn["make_spawn_fn → spawn(subtask) · runner.py"]
        W["wiring_factory(subtask, model)<br/>(injectable seam → offline-testable)"]
        W --> Coll["FindingCollector()<br/>(one per spawn — isolation)"]
        W --> Srv["build_finding_server(collector)<br/>in-process MCP: record_finding"]
        W --> Opt["build_spawn_options(role, server)"]
        Opt --> WF["_with_finding(subagent(role))<br/>role tools + record_finding<br/>+ FINDING_INSTRUCTIONS"]
        DP["_delegation_prompt(role, subtask.prompt)"]

        Coll --> Drive
        Srv --> Drive
        Opt --> Drive
        DP --> Drive
        Drive["asyncio.wait_for(<br/>run_support_agent(prompt, options, runner=query_fn),<br/>timeout)"]
        Drive -->|"TimeoutError"| Partial["log → return partial"]
        Drive --> JSON["findings_to_json(collector.findings)"]
        Partial --> JSON
    end

    JSON --> Ret([JSON blob → back to run_research])

    subgraph SDK["Agent SDK execution — agent/sdk_agent.run_support_agent → claude_agent_sdk.query"]
        Coord["Coordinator agent<br/>(allowed_tools: Task)"]
        Coord -->|"Task(subagent_type=role)"| Subagent["Role subagent<br/>web_search · doc_search · document_analysis"]
        Subagent -->|"role tools"| Tools["WebSearch / WebFetch<br/>Read / Grep / Glob"]
        Subagent -->|"record_finding(Finding)"| Handler["in-process MCP handler"]
        Handler -->|"model_validate + append"| CollDB[("FindingCollector")]
        Subagent --> RM["ResultMessage ends the turn<br/>(termination ≠ parsing prose)"]
    end

    Drive ==>|"drives"| Coord
    CollDB -.->|"same object"| Coll
```

> **Why the relay works:** Task-spawned subagents inherit the parent `ClaudeAgentOptions.mcp_servers`,
> so the subagent can call `mcp__research__record_finding`; the handler appends to the per-spawn
> `FindingCollector` closure. (Verified against the Agent SDK docs during review.)

---

## 3. Dynamic sequence — one round, two parallel subagents

Shows the parallel fan-out (wall-clock ≈ slowest subtask, not the sum), structured capture, the
synthesis merge, and the gap-driven decision to refine or finish.

```mermaid
sequenceDiagram
    autonumber
    actor U as User / CLI
    participant R as run_research
    participant G as asyncio.gather
    participant A1 as subagent web_search
    participant A2 as subagent doc_search
    participant C as FindingCollector(s)
    participant SY as synthesize

    U->>R: run_research(query, spawn_fn, synthesize_fn, criteria)
    R->>R: select_subagents + decompose
    R->>G: gather(spawn(st1), spawn(st2))

    par parallel — latency ≈ slowest subtask
        G->>A1: query + Task(web_search) + self-contained prompt
        A1->>C: record_finding × N (structured, attributed)
        A1-->>G: findings JSON
    and
        G->>A2: query + Task(doc_search) + self-contained prompt
        A2->>C: record_finding × M
        A2-->>G: findings JSON
    end

    G-->>R: [json1, json2]
    R->>SY: synthesize_fn(findings dict) — rehydrate then merge
    SY-->>R: provenance markdown (claim→source, conflicts side-by-side)
    R->>R: find_gaps(criteria, answer)

    alt gaps remain & rounds left
        R->>G: gather(gap subtasks) — next refinement round
    else satisfied OR max_rounds hit
        R-->>U: ResearchResult(answer, rounds, gaps) → format_result → stdout
    end
```

---

## File → responsibility legend

| Component | File | Role |
|---|---|---|
| CLI shell | `scripts/run_research.py` | parse args, gate live/dry-run, `asyncio.run`, print |
| Orchestrator | `src/research/coordinator.py` | `run_research`: select → decompose → gather → synthesise → refine (DI, untouched) |
| Live adapters | `src/research/runner.py` | real `spawn_fn`/`synthesize_fn`, `record_finding` MCP server, Task wiring, JSON bridge, timeout |
| SDK harness | `src/agent/sdk_agent.py` | `run_support_agent` consumes the `query()` message stream (SDK owns the loop) |
| Agent specs | `src/research/agents.py` | `COORDINATOR` (tool: `Task`) + role-scoped `SUBAGENTS`; `build_agent_definitions` |
| Findings | `src/research/schemas.py` | `Finding` contract, `finding_tool_def`, `FINDING_INSTRUCTIONS` |
| Synthesis | `src/research/synthesis.py` | group → classify → provenance-preserving markdown |
