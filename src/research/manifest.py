"""Run manifest for crash-recoverable research (SA-24).

A long research run can die mid-flight (process restart, context exhaustion). Without
persisted state it restarts from zero. The coordinator therefore maintains a **run manifest**:
the task list with each task's completion status and its findings, plus phase summaries. It is
checkpointed after every completed subtask, so a resumed run **skips work already done** and
**injects prior findings** into the resumed agent's prompt.

Persistence is **atomic** (write-temp + ``os.replace``): a crash *during* a write can never
leave a half-written manifest that would corrupt the resume — either the old file or the
fully-new file survives.

Exam: D5 TS 5.4.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from research.schemas import Finding

PENDING = "pending"
DONE = "done"


@dataclass
class TaskRecord:
    """One subtask's durable state: its identity, whether it's finished, and its findings."""

    role: str
    scope: str
    status: str = PENDING
    findings: list[Finding] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"role": self.role, "scope": self.scope, "status": self.status,
                "findings": [f.model_dump() for f in self.findings]}

    @classmethod
    def from_json(cls, d: dict) -> "TaskRecord":
        return cls(role=d["role"], scope=d["scope"], status=d.get("status", PENDING),
                   findings=[Finding(**f) for f in d.get("findings", [])])


@dataclass
class RunManifest:
    """The durable record of a whole research run."""

    run_id: str
    query: str
    tasks: list[TaskRecord] = field(default_factory=list)
    phase_summaries: list[str] = field(default_factory=list)

    @classmethod
    def new(cls, run_id: str, query: str, tasks: list[tuple[str, str]]) -> "RunManifest":
        """Start a manifest from ``(role, scope)`` pairs — all tasks begin ``pending``."""
        return cls(run_id=run_id, query=query,
                   tasks=[TaskRecord(role=r, scope=s) for r, s in tasks])

    def pending(self) -> list[TaskRecord]:
        return [t for t in self.tasks if t.status != DONE]

    def completed(self) -> list[TaskRecord]:
        return [t for t in self.tasks if t.status == DONE]

    def is_complete(self) -> bool:
        return all(t.status == DONE for t in self.tasks)

    def _find(self, scope: str) -> TaskRecord:
        for t in self.tasks:
            if t.scope == scope:
                return t
        raise KeyError(f"no task with scope {scope!r}")

    def mark_done(self, scope: str, findings: list[Finding]) -> None:
        """Record a subtask's findings and flag it done (idempotent — re-marking is a no-op
        overwrite, so a resumed run that re-touches a task can't corrupt prior state)."""
        task = self._find(scope)
        task.findings = list(findings)
        task.status = DONE

    def completed_findings(self) -> list[Finding]:
        """All findings gathered so far, across completed tasks — the resume context."""
        out: list[Finding] = []
        for t in self.completed():
            out.extend(t.findings)
        return out

    def to_json(self) -> dict:
        return {"run_id": self.run_id, "query": self.query,
                "tasks": [t.to_json() for t in self.tasks],
                "phase_summaries": list(self.phase_summaries)}

    @classmethod
    def from_json(cls, d: dict) -> "RunManifest":
        return cls(run_id=d["run_id"], query=d["query"],
                   tasks=[TaskRecord.from_json(t) for t in d.get("tasks", [])],
                   phase_summaries=list(d.get("phase_summaries", [])))


def save_manifest(manifest: RunManifest, path: str | Path) -> None:
    """Persist the manifest **atomically**: write to a temp file, then ``os.replace`` it over
    the target (an atomic rename on the same filesystem). A crash mid-write leaves either the
    previous manifest or the complete new one — never a truncated, unparseable file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(manifest.to_json(), indent=2), encoding="utf-8")
    os.replace(tmp, path)  # atomic rename


def load_manifest(path: str | Path) -> RunManifest:
    return RunManifest.from_json(json.loads(Path(path).read_text(encoding="utf-8")))


def resume_prompt(manifest: RunManifest, task: TaskRecord) -> str:
    """Build a self-contained prompt for resuming ``task``, injecting the findings already
    gathered so the resumed agent doesn't redo earlier work or lose prior context."""
    lines = [f"Resuming research run {manifest.run_id}.",
             f"Original question: {manifest.query}",
             f"YOUR SCOPE: {task.scope}"]
    done = manifest.completed_findings()
    if done:
        lines.append("Already established by earlier subtasks (do NOT re-derive these):")
        for fnd in done:
            src = f" [{fnd.source}]" if fnd.source else ""
            lines.append(f"  - {fnd.claim}{src}")
    if manifest.phase_summaries:
        lines.append("Prior phase summaries:")
        lines.extend(f"  - {s}" for s in manifest.phase_summaries)
    return "\n".join(lines)
