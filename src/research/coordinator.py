"""Coordinator logic: decompose → spawn in parallel → synthesise → refine (SA-21).

This is the deterministic, offline-testable core of the orchestration. The live spawning
is injected (``spawn_fn``) so the planning/decomposition/refinement logic is exercised
without the SDK or any network — the real ``spawn_fn`` issues parallel ``Task`` calls.

Three design points the exam (D1 TS 1.2/1.3/1.6) cares about:

1. **Dynamic subagent selection** — the coordinator picks *which* roles to spawn from the
   question, instead of always firing all four.
2. **Scope-partitioning decomposition** — subtasks have non-overlapping scopes, and each
   prompt states a GOAL and QUALITY CRITERIA, never a step-by-step procedure. The classic
   failure is decomposing too *narrowly* (see ``naive_decompose`` / ``is_too_narrow``):
   each subagent gets a sliver, no one owns the synthesis, and gaps fall through.
3. **Parallelism is the point** — independent subtasks run concurrently in ONE response, so
   wall-clock latency is the slowest single subtask, not their sum (``latency_seconds``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable

from research.agents import SUBAGENTS, subagent

# --- subtask value object ---------------------------------------------------


@dataclass(frozen=True)
class Subtask:
    """One unit of delegated research.

    ``prompt`` MUST be self-contained: a subagent inherits no coordinator context, so the
    prompt carries every fact, the goal, and the quality bar. ``role`` selects the scoped
    subagent. ``scope`` is the slice of the question this subtask owns — used to check the
    decomposition partitions the question without overlap.
    """

    role: str
    scope: str
    prompt: str


# --- dynamic subagent selection ---------------------------------------------

# Cheap keyword routing from the question to research modes. A real coordinator would let
# the model choose; this deterministic mapping makes selection testable and is good enough
# to demonstrate that selection is dynamic rather than "always spawn everything".
_ROLE_SIGNALS = {
    "web_search": ("latest", "current", "news", "today", "recent", "online", "competitor"),
    "doc_search": ("policy", "internal", "knowledge base", "kb", "runbook", "docs", "our"),
    "document_analysis": ("invoice", "contract", "warranty", "attached", "document", "pdf"),
}


def select_subagents(query: str) -> list[str]:
    """Pick the subagent roles this question needs (dynamic, not all-four-always).

    ``synthesis`` is appended whenever more than one researcher is chosen — someone has to
    own merging their findings. If nothing matches, fall back to a single web search so the
    question is always attempted.
    """
    q = query.lower()
    roles = [role for role, signals in _ROLE_SIGNALS.items()
             if any(s in q for s in signals)]
    if not roles:
        roles = ["web_search"]
    if len(roles) > 1:
        roles.append("synthesis")
    return roles


# --- decomposition ----------------------------------------------------------


def _subtask_prompt(query: str, role: str, scope: str) -> str:
    """Build a self-contained, goal-oriented subtask prompt (goal + quality criteria, no
    procedure). The subagent inherits nothing, so the original question is restated here."""
    return (
        f"Research question (full context): {query}\n"
        f"YOUR SCOPE (do not stray outside it): {scope}\n"
        "GOAL: produce findings that answer your scope and nothing else.\n"
        "QUALITY CRITERIA: cite a source for every claim; flag anything you could not "
        "confirm; do not pad with out-of-scope material.\n"
        "Decide your own method — these are outcomes, not steps."
    )


def decompose(query: str, roles: list[str]) -> list[Subtask]:
    """Partition ``query`` into one non-overlapping subtask per researcher role.

    ``synthesis`` is a *merge* role, not a research slice, so it is not given a scope here —
    it consumes the others' findings in ``run_research``. Each research role owns a distinct
    facet of the question; the prompts are goal+criteria, never procedures.
    """
    researchers = [r for r in roles if r != "synthesis"]
    subtasks: list[Subtask] = []
    for role in researchers:
        scope = _SCOPE_BY_ROLE.get(role, f"the {role.replace('_', ' ')} angle of the question")
        subtasks.append(Subtask(role=role, scope=scope, prompt=_subtask_prompt(query, role, scope)))
    return subtasks


_SCOPE_BY_ROLE = {
    "web_search": "external/public information and current state of the world",
    "doc_search": "internal policy and knowledge-base grounding",
    "document_analysis": "the specific attached document(s)",
}


def naive_decompose(query: str, n: int) -> list[Subtask]:
    """The FAILURE mode: chop the question into ``n`` tiny same-role slivers.

    Reproduced deliberately so the test suite shows what too-narrow decomposition looks
    like — every subtask is the same role with a micro-scope, so they overlap in role, no
    one owns synthesis, and the prompts are procedural fragments. ``is_too_narrow`` flags it.
    """
    return [
        Subtask(
            role="web_search",
            scope=f"sub-point {i + 1} of {n}",
            prompt=f"Look up detail #{i + 1} for: {query}",  # procedural fragment, not a goal
        )
        for i in range(n)
    ]


def is_too_narrow(subtasks: list[Subtask], *, max_per_role: int = 2) -> bool:
    """A decomposition is too narrow when many subtasks pile onto ONE role (slivers of the
    same angle) rather than partitioning the question across complementary roles."""
    if not subtasks:
        return False
    counts: dict[str, int] = {}
    for st in subtasks:
        counts[st.role] = counts.get(st.role, 0) + 1
    return max(counts.values()) > max_per_role


def scopes_overlap(subtasks: list[Subtask]) -> bool:
    """True if any two subtasks claim the same scope — decomposition must partition, not
    duplicate. Used by tests to assert non-overlapping scopes."""
    scopes = [st.scope for st in subtasks]
    return len(scopes) != len(set(scopes))


# --- latency model: parallel vs sequential ----------------------------------


def latency_seconds(subtasks: list[Subtask], *, mode: str = "parallel",
                    per_task: float = 1.0) -> float:
    """Wall-clock for running ``subtasks``.

    ``parallel`` (the point of spawning in one response): the slowest single subtask, since
    they run concurrently → ``per_task``. ``sequential``: the sum → ``n * per_task``. With
    uniform ``per_task`` that's ``per_task`` vs ``len * per_task`` — the speedup is the fan-out
    width.
    """
    n = len(subtasks)
    if n == 0:
        return 0.0
    if mode == "parallel":
        return per_task
    if mode == "sequential":
        return n * per_task
    raise ValueError(f"unknown latency mode: {mode!r}")


# --- iterative refinement loop ----------------------------------------------


@dataclass
class ResearchResult:
    """Outcome of an orchestrated research run."""

    answer: str
    findings: dict[str, str] = field(default_factory=dict)  # role -> finding text
    rounds: int = 0
    gaps: list[str] = field(default_factory=list)


def find_gaps(criteria: list[str], answer: str) -> list[str]:
    """Quality criteria not yet satisfied by ``answer`` (case-insensitive substring check).

    Drives the refinement loop: each unmet criterion becomes a follow-up subtask scope. A
    real coordinator would have the synthesis agent judge coverage; this keeps it
    deterministic and offline-testable.
    """
    low = answer.lower()
    return [c for c in criteria if c.lower() not in low]


SpawnFn = Callable[[Subtask], Awaitable[str]]
SynthesizeFn = Callable[[dict[str, str]], Awaitable[str]]


async def run_research(
    query: str,
    *,
    spawn_fn: SpawnFn,
    synthesize_fn: SynthesizeFn,
    criteria: list[str] | None = None,
    max_rounds: int = 3,
) -> ResearchResult:
    """Orchestrate one research question end-to-end.

    Per round: select roles → decompose → spawn every subtask via ``spawn_fn`` (the real one
    fans out parallel ``Task`` calls) → synthesise. If ``criteria`` remain unmet, run another
    round that targets ONLY the gaps, until they're met or ``max_rounds`` is hit. The loop is
    bounded by an explicit round cap — a logged safety net, not the primary stop condition
    (it stops early once criteria are satisfied).
    """
    import asyncio

    criteria = criteria or []
    roles = select_subagents(query)
    subtasks = decompose(query, roles)

    findings: dict[str, str] = {}
    answer = ""
    gaps: list[str] = []
    rounds = 0
    for _ in range(max_rounds):
        rounds += 1
        # Spawn the round's subtasks concurrently — this is what the parallel Task fan-out
        # buys us (latency_seconds(parallel) == one subtask, not the sum).
        results = await asyncio.gather(*(spawn_fn(st) for st in subtasks))
        for st, text in zip(subtasks, results):
            findings[st.role] = text
        answer = await synthesize_fn(findings)

        gaps = find_gaps(criteria, answer)
        if not gaps:
            break
        # Refine: next round targets only the unmet criteria, as fresh self-contained tasks.
        subtasks = [
            Subtask(role="web_search", scope=f"unmet criterion: {gap}",
                    prompt=_subtask_prompt(query, "web_search", f"close this gap: {gap}"))
            for gap in gaps
        ]

    return ResearchResult(answer=answer, findings=findings, rounds=rounds, gaps=gaps)


# Re-exported so callers can introspect the available roles without reaching into agents.py.
RESEARCHER_ROLES = tuple(a.name for a in SUBAGENTS if a.name != "synthesis")


def describe_role(role: str) -> str:
    """One-line description of a subagent role (delegates to the spec)."""
    return subagent(role).description
