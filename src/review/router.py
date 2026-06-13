"""Route extractions to human review, and audit the rest (SA-20).

Send to the review queue anything that is **low-confidence** (below the calibrated
threshold), **ambiguous** (an `unclear`/`other` enum), or built on **contradictory source
data** (SA-18 `conflict_detected`). The high-confidence remainder is accepted — but a
**stratified random sample** of it is still audited, so the ongoing error rate is measured
and novel failure patterns are caught instead of silently accumulating.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from extraction.confidence import low_confidence_fields

REVIEW = "review"
ACCEPT = "accept"


@dataclass
class RoutingDecision:
    route: str
    reasons: list[str] = field(default_factory=list)


def route(confidence: dict[str, float], *, threshold: float,
          conflict_detected: bool = False, ambiguous_fields: tuple[str, ...] = ()) -> RoutingDecision:
    reasons: list[str] = []
    low = low_confidence_fields(confidence, threshold)
    if low:
        reasons.append(f"low confidence: {low}")
    if conflict_detected:
        reasons.append("contradictory source data")
    if ambiguous_fields:
        reasons.append(f"ambiguous fields: {list(ambiguous_fields)}")
    return RoutingDecision(REVIEW if reasons else ACCEPT, reasons)


def enqueue(item: dict, path: str | Path) -> None:
    """Append one item to the JSONL review queue."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(item, default=str) + "\n")


def read_queue(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line]


def _stable_order(value: Any) -> str:
    return hashlib.md5(str(value).encode()).hexdigest()


def stratified_audit_sample(items: list[dict], *, stratum_key: Callable[[dict], Any],
                            id_key: Callable[[dict], Any], rate: float = 0.1) -> list[dict]:
    """Deterministic stratified sample of accepted (high-confidence) items for ongoing audit:
    ~``rate`` of each stratum (at least 1), chosen by a stable hash so every doc-type segment
    is represented and the selection is reproducible."""
    strata: dict[Any, list[dict]] = defaultdict(list)
    for it in items:
        strata[stratum_key(it)].append(it)
    sampled: list[dict] = []
    for group in strata.values():
        ordered = sorted(group, key=lambda it: _stable_order(id_key(it)))
        k = max(1, round(rate * len(group))) if group else 0
        sampled.extend(ordered[:k])
    return sampled
