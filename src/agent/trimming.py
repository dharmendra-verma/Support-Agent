"""Tool-output trimming + context assembly (SA-28).

A 40-field order lookup bloats the context window when only ~5 fields matter. ``trim_output``
projects a tool result down to the relevant fields *before* it enters context, and
``trim_savings`` measures the token reduction so the saving is evidenced, not assumed.

``assemble_context`` lays out a request so the **key summaries come first, under explicit
section headers** — the case-facts block (SA-28 ``case_facts``) on top, then the summarized
history — countering the lost-in-the-middle effect.
"""
from __future__ import annotations

import json
from typing import Any, Sequence

_CHARS_PER_TOKEN = 4  # rough GPT/Claude-style estimate; good enough to measure relative savings


def estimate_tokens(value: Any) -> int:
    """Cheap token estimate for a JSON-serialisable value (~4 chars/token)."""
    text = value if isinstance(value, str) else json.dumps(value, default=str, sort_keys=True)
    return max(1, len(text) // _CHARS_PER_TOKEN)


def trim_output(output: dict, relevant: Sequence[str]) -> dict:
    """Keep only ``relevant`` keys from a tool output (missing keys are skipped, not faked).
    The full result still exists upstream; only the trimmed projection enters context."""
    return {k: output[k] for k in relevant if k in output}


def trim_savings(before: dict, after: dict) -> dict:
    """Measure the token reduction from trimming. Returns before/after token estimates, the
    absolute saving, and the percent saved (0 when ``before`` is empty)."""
    b, a = estimate_tokens(before), estimate_tokens(after)
    saved = b - a
    pct = round(100 * saved / b, 1) if b else 0.0
    return {"before_tokens": b, "after_tokens": a, "saved_tokens": saved, "pct_saved": pct}


def assemble_context(case_facts_block: str, sections: Sequence[tuple[str, str]]) -> str:
    """Assemble the request body with key facts FIRST, then labelled sections.

    The case-facts block is placed at the very top (outside, and ahead of, the summarized
    history) so authoritative figures lead the context; each subsequent section gets an
    explicit ``## header``. Empty pieces are dropped.
    """
    parts: list[str] = []
    if case_facts_block.strip():
        parts.append(case_facts_block)
    for header, body in sections:
        if body and body.strip():
            parts.append(f"## {header}\n{body}")
    return "\n\n".join(parts)
