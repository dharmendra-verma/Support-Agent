"""Coordinator + role-scoped subagent definitions (SA-21).

The orchestration has two tiers:

* a **coordinator** whose only job is to *plan and delegate* — its sole tool is ``Task``,
  the SDK's subagent-spawning tool. It never does research itself; it decomposes the
  question, fans out subagents in parallel, and hands their findings to synthesis.
* four **subagents**, each scoped to one research mode with a *minimal* toolset
  (selection reliability degrades with tool count — see SA-13 / `tooling.py`). A subagent
  inherits **nothing** from the coordinator: its system prompt fully defines its role and
  its task prompt carries every fact it needs.

``AgentSpec`` is an SDK-independent value object so this module imports without the SDK
installed; ``build_agent_definitions()`` projects the specs into real
``claude_agent_sdk.AgentDefinition`` objects lazily (exam D1 TS 1.2/1.3/1.6).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentSpec:
    """SDK-independent description of one agent in the orchestration.

    Projected into ``claude_agent_sdk.AgentDefinition`` by ``build_agent_definitions``.
    ``tools`` is intentionally tiny per role — a subagent offered only the tools it needs
    selects them far more reliably than one handed the full set.
    """

    name: str
    description: str
    prompt: str
    tools: tuple[str, ...]
    model: str = "sonnet"


# The coordinator's ONLY tool is Task: it plans and delegates, never researches directly.
COORDINATOR = AgentSpec(
    name="coordinator",
    description="Plans a research question and delegates to subagents; does no research itself.",
    prompt=(
        "You are a research coordinator. You do NOT research anything yourself. "
        "Decompose the question into non-overlapping subtasks, spawn one subagent per "
        "subtask in PARALLEL (issue every Task call in a single response so they run "
        "concurrently), then collect and synthesise their findings. Each subagent shares "
        "no context with you — give every Task a self-contained prompt stating its goal and "
        "what 'done' looks like, never step-by-step procedures."
    ),
    tools=("Task",),
)

# Role-scoped subagents. Each is its own context window with a minimal toolset.
SUBAGENTS: tuple[AgentSpec, ...] = (
    AgentSpec(
        name="web_search",
        description="Searches the public web for current, external information.",
        prompt=(
            "You research one narrow question using web search. Return findings with source "
            "URLs. Stay strictly within the scope you are given; do not expand it."
        ),
        tools=("WebSearch", "WebFetch"),
    ),
    AgentSpec(
        name="doc_search",
        description="Searches internal docs/knowledge base for grounded answers.",
        prompt=(
            "You research one narrow question against the internal knowledge base. Cite the "
            "document for each claim. Stay strictly within your assigned scope."
        ),
        tools=("Grep", "Read", "Glob"),
    ),
    AgentSpec(
        name="document_analysis",
        description="Reads and analyses a specific provided document in depth.",
        prompt=(
            "You analyse the specific document(s) named in your task. Extract only what the "
            "task asks for and quote the supporting passages. Do not go beyond the document."
        ),
        tools=("Read",),
    ),
    AgentSpec(
        name="synthesis",
        description="Merges subagent findings into one answer; flags gaps and conflicts.",
        prompt=(
            "You receive findings from several research subagents. Merge them into one "
            "coherent answer, attribute each point to its source, and explicitly call out "
            "gaps and contradictions rather than papering over them. You do no new research."
        ),
        tools=(),
    ),
)

_SUBAGENTS_BY_NAME = {a.name: a for a in SUBAGENTS}


def subagent(name: str) -> AgentSpec:
    """Look up a subagent spec by name (fail-fast on an unknown role)."""
    try:
        return _SUBAGENTS_BY_NAME[name]
    except KeyError:
        raise KeyError(f"unknown subagent role: {name!r}") from None


def build_agent_definitions(specs: list[AgentSpec] | None = None) -> dict:
    """Project specs into ``claude_agent_sdk.AgentDefinition`` (imported lazily).

    Returns a ``{name: AgentDefinition}`` map suitable for ``ClaudeAgentOptions(agents=...)``.
    Keeping the SDK import inside the function means this module stays import-safe with no
    SDK installed and no API key (python-style.md: lazy-import heavy SDKs).
    """
    from claude_agent_sdk import AgentDefinition

    chosen = specs if specs is not None else [COORDINATOR, *SUBAGENTS]
    return {
        spec.name: AgentDefinition(
            description=spec.description,
            prompt=spec.prompt,
            tools=list(spec.tools),
            model=spec.model,
        )
        for spec in chosen
    }
