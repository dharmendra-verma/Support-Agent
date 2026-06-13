"""Provenance-preserving synthesis of research findings (SA-22).

Synthesis is where attribution is usually lost: findings get summarized into prose and the
source-per-claim mapping evaporates, while two credible-but-conflicting numbers get
collapsed into one arbitrary value. This module refuses both.

Findings are grouped by ``topic`` and each group is classified:

* **established** — one value, corroborated by ≥2 independent sources.
* **single** — one value, one source (reported, but not yet corroborated).
* **temporal** — differing values, but each at a *different date*: a value that changed over
  time, NOT a contradiction. Distinguishing this requires the dates (hence they're required).
* **contested** — differing values that genuinely conflict (same date, or an undated value we
  can't safely attribute to change). These are surfaced **side by side with attribution**,
  never silently collapsed.

Rendering is type-appropriate: financial findings → a table, news → prose, technical → a
list. Every claim cites its source.

Exam: D5 TS 5.6 (provenance/citation), D1 TS 1.3 (structured context between agents).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from research.schemas import ContentType, Finding

ESTABLISHED = "established"
SINGLE = "single"
TEMPORAL = "temporal"
CONTESTED = "contested"


@dataclass
class ClaimGroup:
    """All findings about one ``topic``, with a derived corroboration/conflict status."""

    topic: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def sources(self) -> list[str]:
        """Distinct sources backing this topic, in first-seen order (provenance preserved)."""
        seen: dict[str, None] = {}
        for f in self.findings:
            seen.setdefault(f.source, None)
        return list(seen)

    @property
    def distinct_values(self) -> list[str]:
        seen: dict[str, None] = {}
        for f in self.findings:
            if f.value is not None:
                seen.setdefault(f.value, None)
        return list(seen)

    @property
    def status(self) -> str:
        return classify(self.findings)


def classify(findings: list[Finding]) -> str:
    """Corroboration/conflict status for findings about one topic.

    A contradiction is only declared when two findings report *different values at the same
    point in time* (same ``source_date``), or when a differing value is **undated** so we
    cannot prove it reflects change over time. Differing values each at their own date are a
    time series → ``temporal``, never a contradiction.
    """
    values = [f.value for f in findings if f.value is not None]
    distinct = set(values)
    sources = {f.source for f in findings}

    if len(distinct) <= 1:
        return ESTABLISHED if len(sources) >= 2 else SINGLE

    # Multiple distinct values. Same-date disagreement, or a differing undated value, is a
    # genuine conflict; otherwise each value sits at its own date → temporal evolution.
    by_date: dict[str | None, set[str]] = defaultdict(set)
    for f in findings:
        if f.value is not None:
            by_date[f.source_date].add(f.value)
    if any(len(v) > 1 for v in by_date.values()):
        return CONTESTED
    if None in by_date:          # an undated differing value — can't claim it's temporal
        return CONTESTED
    return TEMPORAL


def group_by_topic(findings: list[Finding]) -> list[ClaimGroup]:
    """Group findings by topic, preserving first-seen order of both topics and findings."""
    groups: dict[str, ClaimGroup] = {}
    for f in findings:
        groups.setdefault(f.topic, ClaimGroup(topic=f.topic)).findings.append(f)
    return list(groups.values())


# --- type-appropriate rendering ---------------------------------------------


def _cite(f: Finding) -> str:
    """Source citation for one finding, with date when present."""
    return f"{f.source} ({f.source_date})" if f.source_date else f.source


def _dominant_content_type(group: ClaimGroup) -> ContentType:
    """The content type to render this group as — the first non-OTHER type wins, else OTHER."""
    for f in group.findings:
        if f.content_type is not ContentType.OTHER:
            return f.content_type
    return ContentType.OTHER


def _render_conflict(group: ClaimGroup) -> list[str]:
    """Conflicting values side by side, each attributed — never an arbitrary pick."""
    lines = [f"**{group.topic}** — ⚠️ contested (sources disagree):"]
    for f in group.findings:
        if f.value is not None:
            lines.append(f"  - {f.value} — {_cite(f)}")
    return lines


def _render_financial(group: ClaimGroup) -> list[str]:
    """Financial findings as a table (value | source | date)."""
    lines = [f"**{group.topic}**", "", "| Value | Source | Date |", "| --- | --- | --- |"]
    for f in group.findings:
        lines.append(f"| {f.value if f.value is not None else f.claim} "
                     f"| {f.source} | {f.source_date or '—'} |")
    return lines


def _render_news(group: ClaimGroup) -> list[str]:
    """News findings as prose, each sentence citing its source inline."""
    sentences = [f"{f.claim} [{_cite(f)}]." for f in group.findings]
    return [f"**{group.topic}**", " ".join(sentences)]


def _render_list(group: ClaimGroup) -> list[str]:
    """Technical/other findings as a bulleted list, each item citing its source."""
    lines = [f"**{group.topic}**"]
    for f in group.findings:
        lines.append(f"  - {f.claim} — {_cite(f)}")
    return lines


def render_group(group: ClaimGroup) -> str:
    """Render one topic group: conflicts go side-by-side; otherwise type-appropriately."""
    status = group.status
    if status == CONTESTED:
        body = _render_conflict(group)
    else:
        ctype = _dominant_content_type(group)
        if ctype is ContentType.FINANCIAL:
            body = _render_financial(group)
        elif ctype is ContentType.NEWS:
            body = _render_news(group)
        else:
            body = _render_list(group)
        if status == ESTABLISHED:
            body.append(f"  _well-established: corroborated by {len(group.sources)} sources._")
        elif status == TEMPORAL:
            body.append("  _values differ over time (not a contradiction)._")
        elif status == SINGLE:
            body.append("  _single source — not yet corroborated._")
    return "\n".join(body)


@dataclass
class SynthesisReport:
    """The synthesised report: topic groups plus their classifications. Carries the structured
    groups (so callers can assert on provenance) and renders to markdown on demand."""

    groups: list[ClaimGroup]

    @property
    def contested(self) -> list[ClaimGroup]:
        return [g for g in self.groups if g.status == CONTESTED]

    @property
    def established(self) -> list[ClaimGroup]:
        return [g for g in self.groups if g.status == ESTABLISHED]

    def sources_for(self, topic: str) -> list[str]:
        for g in self.groups:
            if g.topic == topic:
                return g.sources
        return []

    def to_markdown(self) -> str:
        return "\n\n".join(render_group(g) for g in self.groups)


def synthesize(findings: list[Finding]) -> SynthesisReport:
    """Merge findings into a report that preserves claim→source mappings end-to-end, surfaces
    conflicts side-by-side with attribution, and separates established from contested — without
    ever discarding a source or arbitrarily picking among conflicting credible values."""
    return SynthesisReport(groups=group_by_topic(findings))
