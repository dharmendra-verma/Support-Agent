"""Agent scratchpads + phase summaries (SA-24).

Two defenses against long-run context degradation (the "vague typical-patterns" failure):

* **Scratchpad files** — an agent appends its key findings to a known markdown file and reads
  them back for later questions, so important facts live in durable storage instead of decaying
  in a long context window.
* **Phase summaries** — the findings from one exploration phase are condensed into a compact
  summary that is injected into the *next* phase's initial context, so each phase starts
  grounded in concrete prior results rather than re-exploring from scratch.

Scratchpads are append-only markdown (no atomicity needed — each line is independent); the
durable run state that *must* survive a crash mid-write lives in the atomically-persisted
manifest (``manifest.py``).

Exam: D5 TS 5.4.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from research.schemas import Finding

_FINDING_PREFIX = "- "


@dataclass
class Scratchpad:
    """A durable markdown file an agent writes key findings to and reads back later.

    Append-only: each ``record``/``note`` adds one line, so a crash can at worst lose the line
    being written, never corrupt earlier ones. ``key_findings`` parses the recorded claims back
    out for re-grounding a later question.
    """

    path: Path

    def __post_init__(self) -> None:
        self.path = Path(self.path)

    def _append_line(self, line: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def record(self, finding: Finding) -> None:
        """Persist one finding as a key line: claim + source (for later citation)."""
        src = f" [{finding.source}]" if finding.source else ""
        self._append_line(f"{_FINDING_PREFIX}{finding.claim}{src}")

    def note(self, text: str) -> None:
        """Persist a free-form note (e.g. a working hypothesis)."""
        self._append_line(f"{_FINDING_PREFIX}{text}")

    def read(self) -> str:
        return self.path.read_text(encoding="utf-8") if self.path.exists() else ""

    def key_findings(self) -> list[str]:
        """The recorded key-finding lines (without the bullet prefix) — what an agent re-reads
        before answering a follow-up so it relies on logged facts, not a degraded context."""
        return [line[len(_FINDING_PREFIX):] for line in self.read().splitlines()
                if line.startswith(_FINDING_PREFIX)]


def phase_summary(phase_name: str, findings: list[Finding], *, max_items: int = 5) -> str:
    """Condense one phase's findings into a compact, injectable summary line.

    Caps at ``max_items`` claims so the summary stays small enough to prepend to the next
    phase's context without re-bloating it; notes when items were elided so nothing is silently
    dropped.
    """
    if not findings:
        return f"Phase '{phase_name}': no findings."
    shown = findings[:max_items]
    parts = [f"{f.claim} [{f.source}]" if f.source else f.claim for f in shown]
    summary = f"Phase '{phase_name}' ({len(findings)} findings): " + "; ".join(parts)
    if len(findings) > max_items:
        summary += f"; (+{len(findings) - max_items} more)"
    return summary


def next_phase_context(summaries: list[str]) -> str:
    """Assemble prior phase summaries into the initial context for the next phase."""
    if not summaries:
        return ""
    lines = ["[carried forward from earlier phases]"]
    lines.extend(f"- {s}" for s in summaries)
    return "\n".join(lines)
