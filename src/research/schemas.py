"""Structured research findings with provenance (SA-22).

A subagent must return **structured** ``Finding`` objects, not prose, so attribution survives
the hop to synthesis. Each finding cleanly separates **content** (the ``claim`` and its
``evidence`` excerpt) from **metadata** (``source``, ``source_date``, ``content_type``) — the
metadata is what lets synthesis cite per claim, place conflicting values side-by-side, and
tell a *temporal change* apart from a *contradiction* (which requires the date).

The model's JSON schema is projected into a tool ``input_schema`` (same pattern as the SA-17
extraction contract): a subagent emits findings by *calling* the tool, so the output is
guaranteed-shaped JSON, never free text that loses its sources.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class ContentType(str, Enum):
    """How a finding should be rendered downstream — drives type-appropriate formatting."""

    FINANCIAL = "financial"   # numbers/stats → table
    NEWS = "news"             # events/announcements → prose
    TECHNICAL = "technical"   # specs/steps/facts → list
    OTHER = "other"


class Finding(BaseModel):
    """One atomic, attributable research result.

    Content vs metadata is deliberate: ``claim``/``evidence`` are *what was found*;
    ``source``/``source_date``/``content_type`` are *where and when*. ``topic`` is the key
    synthesis groups on to compare findings about the same thing. ``value`` is the
    comparable datum (e.g. a statistic) when the claim asserts one — it's what conflict
    detection compares, so two sources reporting different numbers for the same topic are
    caught instead of silently collapsed.
    """

    topic: str                          # what this finding is about (grouping key)
    claim: str                          # the assertion (content)
    source: str                         # URL or document name (metadata) — never dropped
    evidence: str | None = None         # supporting excerpt (content)
    source_date: str | None = None      # ISO 8601 publication/collection date (metadata)
    value: str | None = None            # comparable datum for conflict detection, if any
    content_type: ContentType = ContentType.OTHER


FINDING_TOOL_NAME = "record_finding"


def finding_tool_def() -> dict:
    """Anthropic tool def whose ``input_schema`` is the Finding contract. Subagents are
    required to call this (one call per finding) so every result arrives structured and
    attributed — content separated from metadata."""
    return {
        "name": FINDING_TOOL_NAME,
        "description": (
            "Record ONE research finding as structured data. Always include the source "
            "(URL or document name) and, when known, the publication/collection date — these "
            "are required for citation and for telling a value that changed over time apart "
            "from a genuine contradiction. Put the comparable number/stat in `value` when the "
            "claim asserts one. Do not summarize multiple sources into one finding."
        ),
        "input_schema": Finding.model_json_schema(),
    }


# Prompt fragment given to every research subagent so its outputs are structured findings.
FINDING_INSTRUCTIONS = (
    "Return your results ONLY as record_finding tool calls — one call per discrete claim. "
    "Every finding MUST carry its source and (when available) its date. Never merge two "
    "sources into one finding; if two sources disagree, record both separately so the "
    "conflict is preserved for synthesis."
)
