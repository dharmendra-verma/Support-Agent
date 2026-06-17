"""Live production adapters for the research coordinator (SA-39).

``research.coordinator.run_research`` is the deterministic, offline-tested core: it selects
roles, decomposes the question into non-overlapping subtasks, fans them out **concurrently**
(``asyncio.gather``), synthesises, and refines unmet criteria. Its ``spawn_fn``/``synthesize_fn``
are *injected* so that core never imports the SDK. This module supplies the **real**
implementations and leaves ``run_research`` untouched:

* :func:`make_spawn_fn` — launches ONE role-scoped subagent via the Agent SDK ``Task`` tool,
  using the ``AgentDefinition``s from :func:`research.agents.build_agent_definitions`. The
  subagent inherits **no** coordinator context — the full ``Subtask.prompt`` is passed in — and
  is offered ONLY its role-scoped tools plus the in-process ``record_finding`` tool. Findings
  are captured **structurally** (one ``record_finding`` call per claim), never by parsing prose,
  so provenance survives the hop. The genuine parallelism (wall-clock ≈ slowest subtask, not the
  sum) comes from ``run_research``'s ``asyncio.gather`` firing these concurrently.
* :func:`make_synthesize_fn` — deserialises every subtask's findings and merges them through
  :func:`research.synthesis.synthesize`, preserving claim→source mappings and surfacing
  conflicts side by side.

The string-typed coordinator contract (``SpawnFn`` returns ``str``; ``SynthesizeFn`` takes
``dict[str, str]``) is bridged with JSON: a subagent's ``list[Finding]`` is serialised to JSON
on the way out and rehydrated for synthesis on the way in. This keeps ``run_research`` and its
test suite unchanged.

The SDK is imported lazily (python-style.md), so this module — and the CLI that imports it —
loads with no SDK installed and no API key. Exam: D1 TS 1.2 (parallel spawning), D1 TS 1.3
(Task tool + role-scoped tools, self-contained context), D5 TS 5.6 (provenance in the answer).
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import replace

from research.agents import COORDINATOR, SUBAGENTS, build_agent_definitions, subagent
from research.coordinator import ResearchResult, Subtask
from research.schemas import Finding, finding_tool_def
from research.synthesis import synthesize

logger = logging.getLogger("resolvedesk.research.runner")

# In-process MCP server exposing record_finding. The fully-qualified tool name the SDK exposes
# is ``mcp__<server>__<tool>`` — both the subagent (which calls it) and ``allowed_tools`` (which
# permits it) must reference this exact name.
FINDING_SERVER_NAME = "research"
FINDING_TOOL_NAME = finding_tool_def()["name"]  # one source of truth (schemas.record_finding)
RECORD_FINDING_TOOL = f"mcp__{FINDING_SERVER_NAME}__{FINDING_TOOL_NAME}"


# --- finding capture --------------------------------------------------------


class FindingCollector:
    """Accumulates the structured findings a subagent emits via ``record_finding``.

    One collector per spawn so concurrent subtasks (run together by ``asyncio.gather``) never
    cross-contaminate each other's findings.
    """

    def __init__(self) -> None:
        self.findings: list[Finding] = []

    def add(self, args: dict) -> Finding:
        """Validate one ``record_finding`` payload against the :class:`Finding` contract and
        keep it. Validation failures fail fast — a malformed finding is a contract bug, not data
        to swallow (python-style.md)."""
        finding = Finding.model_validate(args)
        self.findings.append(finding)
        return finding


def build_finding_server(collector: FindingCollector):
    """Build the in-process ``record_finding`` SDK MCP server backed by ``collector``.

    Reuses the ``schemas.finding_tool_def`` contract (name + input_schema) so the tool the
    subagent calls is the exact ``Finding`` shape — no second schema definition. Imported lazily
    so this module stays import-safe without the SDK installed.
    """
    from claude_agent_sdk import create_sdk_mcp_server, tool

    contract = finding_tool_def()

    @tool(FINDING_TOOL_NAME, contract["description"], contract["input_schema"])
    async def record_finding(args: dict) -> dict:
        try:
            collector.add(args)
        except Exception as exc:  # surface a malformed finding back to the subagent to retry
            return {"content": [{"type": "text", "text": f"invalid finding: {exc}"}],
                    "is_error": True}
        return {"content": [{"type": "text", "text": "finding recorded"}]}

    return create_sdk_mcp_server(name=FINDING_SERVER_NAME, version="1.0.0", tools=[record_finding])


# --- agent wiring (Task + role-scoped tools) --------------------------------


def finding_enabled_specs():
    """The subagent specs with ``record_finding`` added to every *researcher*'s toolset.

    Researchers must be able to emit structured findings; the merge-only ``synthesis`` role and
    the ``coordinator`` (whose sole tool stays ``Task``) are left exactly as declared. Returned as
    SDK-independent ``AgentSpec``s so the wiring invariant can be asserted offline, and projected
    into real ``AgentDefinition``s by :func:`build_agent_definitions` only when the SDK is present.
    """
    enabled = []
    for spec in SUBAGENTS:
        if spec.name == "synthesis":
            enabled.append(spec)
            continue
        enabled.append(replace(
            spec,
            prompt=spec.prompt + "\n\n" + finding_tool_def()["description"],
            tools=spec.tools + (RECORD_FINDING_TOOL,),
        ))
    return enabled


def build_spawn_options(role: str, finding_server, *, model: str | None = None,
                        max_turns: int = 12):
    """Assemble ``ClaudeAgentOptions`` for delegating ONE subtask to the ``role`` subagent.

    The queried (coordinator) agent's only tool is ``Task``; it spawns the role-scoped subagent,
    which carries only its own minimal tools plus ``record_finding``. ``permission_mode`` is
    ``bypassPermissions`` so the autonomous CLI run isn't blocked on interactive approval. SDK
    imported lazily.
    """
    from claude_agent_sdk import ClaudeAgentOptions

    spec = subagent(role)
    enabled = replace(
        spec,
        prompt=spec.prompt + "\n\n" + finding_tool_def()["description"],
        tools=spec.tools + (RECORD_FINDING_TOOL,),
        model=model or spec.model,
    )
    return ClaudeAgentOptions(
        system_prompt=COORDINATOR.prompt,
        allowed_tools=["Task", RECORD_FINDING_TOOL],
        agents=build_agent_definitions([enabled]),
        mcp_servers={FINDING_SERVER_NAME: finding_server},
        permission_mode="bypassPermissions",
        max_turns=max_turns,
    )


def _delegation_prompt(role: str, subtask_prompt: str) -> str:
    """Tell the coordinator to delegate this one subtask to ``role`` via the Task tool, passing
    the self-contained subtask prompt through verbatim (the subagent inherits nothing else)."""
    return (
        f"Use the Task tool to delegate the following research subtask to the '{role}' subagent "
        f"(subagent_type='{role}'). Do no research yourself. Pass the prompt below to the "
        f"subagent verbatim; once it has returned its record_finding calls, stop.\n\n"
        f"{subtask_prompt}"
    )


# --- JSON bridge over the string-typed coordinator contract -----------------


def findings_to_json(findings: list[Finding]) -> str:
    """Serialise a subagent's findings to the JSON string ``run_research`` carries as the per-
    subtask result (enum values are emitted as plain strings via ``mode='json'``)."""
    return json.dumps([f.model_dump(mode="json") for f in findings])


def findings_from_json(blob: str) -> list[Finding]:
    """Rehydrate :class:`Finding` objects from a per-subtask JSON blob. A blank or unparseable
    blob yields no findings rather than raising — a subagent that recorded nothing is a valid
    empty result, not a crash."""
    if not blob:
        return []
    try:
        raw = json.loads(blob)
    except json.JSONDecodeError:
        logger.warning("could not parse findings blob; treating as empty: %.80r", blob)
        return []
    return [Finding.model_validate(item) for item in raw]


# --- real spawn_fn / synthesize_fn ------------------------------------------


def make_spawn_fn(*, query_fn=None, per_subtask_timeout: float = 120.0,
                  model: str | None = None):
    """Build the real ``spawn_fn``: one call → one role-scoped subagent → its findings as JSON.

    ``query_fn`` defaults to ``claude_agent_sdk.query`` (injected in tests). A hung subagent is
    bounded by ``per_subtask_timeout`` so a single stuck Task can never hang the blocking CLI
    forever; on timeout whatever was collected so far is returned (partial results), and the
    missing coverage surfaces as an unmet criterion in ``run_research`` (ties into SA-23).
    """
    async def spawn(subtask: Subtask) -> str:
        collector = FindingCollector()
        server = build_finding_server(collector)
        options = build_spawn_options(subtask.role, server, model=model)
        prompt = _delegation_prompt(subtask.role, subtask.prompt)

        # Reuse the SDK consumption loop (sdk_agent.run_support_agent); findings are captured as
        # a side effect of the in-process record_finding tool, so its return text is discarded.
        from agent.sdk_agent import run_support_agent

        try:
            await asyncio.wait_for(
                run_support_agent(prompt, options=options, runner=query_fn),
                timeout=per_subtask_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "subagent role=%s scope=%r timed out after %.0fs; returning %d partial finding(s)",
                subtask.role, subtask.scope, per_subtask_timeout, len(collector.findings),
            )
        return findings_to_json(collector.findings)

    return spawn


def make_synthesize_fn():
    """Build the real ``synthesize_fn``: rehydrate all subtasks' findings and merge them through
    :func:`research.synthesis.synthesize`, returning provenance-preserving markdown (claim→source,
    conflicts side by side). Pure and offline — synthesis is deterministic Python."""
    async def synth(findings: dict[str, str]) -> str:
        merged: list[Finding] = []
        for blob in findings.values():
            merged.extend(findings_from_json(blob))
        return synthesize(merged).to_markdown()

    return synth


# --- offline dry-run spawn --------------------------------------------------


async def dry_run_spawn_fn(subtask: Subtask) -> str:
    """A fake ``spawn_fn`` that fabricates one structured finding per subtask, with no SDK and no
    network — used by ``--dry-run`` to exercise the full decompose → spawn → synthesise → refine
    flow (and its provenance rendering) offline."""
    finding = Finding(
        topic=subtask.scope,
        claim=f"[dry-run] simulated finding for scope: {subtask.scope}",
        source="dry-run://offline",
        evidence=f"role={subtask.role}",
    )
    return findings_to_json([finding])


# --- result formatting (shared by the CLI) ----------------------------------


def format_result(result: ResearchResult, *, as_json: bool = False) -> str:
    """Render a :class:`ResearchResult` for the CLI: the final answer, the rounds taken, and any
    unmet coverage gaps. ``--json`` emits the same three fields as machine-readable JSON."""
    if as_json:
        return json.dumps(
            {"answer": result.answer, "rounds": result.rounds, "gaps": result.gaps}, indent=2,
        )
    lines = [result.answer or "(no answer produced)", "", f"Rounds: {result.rounds}"]
    if result.gaps:
        lines.append("Unmet coverage gaps:")
        lines.extend(f"  - {gap}" for gap in result.gaps)
    else:
        lines.append("Coverage gaps: none")
    return "\n".join(lines)
