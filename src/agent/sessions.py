"""Session resumption & forking for support conversations (SA-9).

Maps onto the Claude Agent SDK session model:
  - resume-by-name   -> ``ClaudeAgentOptions(resume=<session_id>)``
  - fork_session     -> ``ClaudeAgentOptions(resume=<id>, fork_session=True)`` from a baseline
  - fresh + summary  -> a NEW session seeded with a structured ``CaseSummary`` when prior tool
                        results are stale (resuming would feed the model stale context).

This module owns the durable layer — named persistence, fork independence, stale detection,
and case-summary serialization — so the behavior is provable without a live model.
"""
from __future__ import annotations

import copy
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CaseSummary:
    """Durable case facts that survive across sessions and are injected into fresh ones.

    Holds only facts that DON'T go stale (verified customer, the order under discussion,
    established notes). Volatile values (order status, balances) are deliberately excluded —
    the agent must re-fetch them.
    """

    customer_id: str | None = None
    order_id: str | None = None
    durable_facts: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_prompt(self) -> str:
        lines = ["[case summary — verified facts carried into this session]"]
        if self.customer_id:
            lines.append(f"- verified customer: {self.customer_id}")
        if self.order_id:
            lines.append(f"- order under discussion: {self.order_id}")
        for k, v in self.durable_facts.items():
            lines.append(f"- {k}: {v}")
        for n in self.notes:
            lines.append(f"- note: {n}")
        lines.append("Re-fetch any volatile data (order status, balances) with tools — "
                     "do not assume prior values.")
        return "\n".join(lines)


@dataclass
class Session:
    """A named support conversation: history + durable summary + volatile snapshots."""

    name: str
    messages: list[dict] = field(default_factory=list)
    summary: CaseSummary = field(default_factory=CaseSummary)
    # last-seen volatile tool results, keyed e.g. "order:12345" -> {"status": "processing"}
    snapshots: dict[str, Any] = field(default_factory=dict)

    def inform_changes(self, changes: list[str]) -> None:
        """Append a structured change notice so a resumed session re-analyzes only what
        changed (targeted re-analysis)."""
        bullet = "; ".join(changes)
        self.messages.append({
            "role": "user",
            "content": (f"[case update] These changed since we last spoke: {bullet}. "
                        "Re-analyze only what's affected."),
        })


class SessionNotFound(KeyError):
    """No persisted session with that name."""


@dataclass
class SessionStore:
    """Named, on-disk persistence — one JSON file per session (resume-by-name)."""

    root: Path

    def _path(self, name: str) -> Path:
        return self.root / f"{name}.json"

    def exists(self, name: str) -> bool:
        return self._path(name).exists()

    def save(self, session: Session) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._path(session.name).write_text(json.dumps(asdict(session), indent=2),
                                            encoding="utf-8")

    def resume(self, name: str) -> Session:
        """Continue a persisted session by name (``--resume <name>`` semantics)."""
        if not self.exists(name):
            raise SessionNotFound(name)
        return _from_dict(json.loads(self._path(name).read_text(encoding="utf-8")))

    def fork(self, name: str, new_name: str) -> Session:
        """Branch an independent session from a baseline. Mutating the fork never affects
        the original (deep copy + separate file)."""
        forked = copy.deepcopy(self.resume(name))
        forked.name = new_name
        self.save(forked)
        return forked


def _from_dict(d: dict) -> Session:
    return Session(
        name=d["name"],
        messages=d.get("messages", []),
        summary=CaseSummary(**d.get("summary", {})),
        snapshots=d.get("snapshots", {}),
    )


def is_stale(session: Session, current: dict[str, Any]) -> bool:
    """True if any snapshotted volatile value differs from the current world.

    ``current`` maps the same keys as ``session.snapshots`` to their current values.
    """
    return any(key in current and current[key] != snap
               for key, snap in session.snapshots.items())


def continue_session(
    session: Session,
    current: dict[str, Any],
    store: SessionStore | None = None,
) -> tuple[str, Session]:
    """Decide **resume** vs **fresh-with-summary**.

    If volatile context is stale, resuming would replay the OLD tool results sitting in the
    conversation history → the model answers from stale facts. Instead, start a FRESH session
    seeded only with the durable ``CaseSummary`` (stale snapshots dropped) so the agent
    re-fetches the current values.

    Returns ``("resume", session)`` or ``("fresh", new_session)``.
    """
    if not is_stale(session, current):
        return ("resume", session)
    fresh = Session(name=f"{session.name}-fresh", summary=copy.deepcopy(session.summary))
    fresh.messages = [{"role": "user", "content": session.summary.to_prompt()}]
    # stale snapshots are intentionally NOT carried into the fresh session
    if store is not None:
        store.save(fresh)
    return ("fresh", fresh)


def to_sdk_options(mode: str, *, session_id: str | None = None, system_prompt: str = "") -> Any:
    """Map a continuation decision to ``ClaudeAgentOptions`` (lazy import).

    resume -> resume that session id; fork -> resume + fork_session; fresh -> a new session.
    """
    from claude_agent_sdk import ClaudeAgentOptions

    if mode == "resume":
        return ClaudeAgentOptions(resume=session_id)
    if mode == "fork":
        return ClaudeAgentOptions(resume=session_id, fork_session=True)
    return ClaudeAgentOptions(system_prompt=system_prompt)  # fresh
