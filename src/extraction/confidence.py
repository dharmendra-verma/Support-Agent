"""Field-level confidence + calibration against labels (SA-20).

Raw self-reported confidence is poorly calibrated, so the routing **threshold is derived
from a labeled validation set**, not picked arbitrarily: choose the lowest confidence cutoff
whose kept population meets a target error rate. Accuracy is then reported by document type
AND field, because a 97% aggregate can hide a field/doc-type that's systematically wrong.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


@dataclass
class LabeledSample:
    """One field's prediction on the validation set: its confidence and whether it matched
    the human label."""

    confidence: float
    correct: bool


def calibrate_threshold(samples: list[LabeledSample], *, target_error: float = 0.05) -> float:
    """Lowest confidence threshold T such that, among predictions with confidence >= T, the
    error rate is <= ``target_error``. Returns 1.0 if no cutoff achieves it (route everything
    to review). Threshold comes from the labels — never hand-picked."""
    for threshold in sorted({s.confidence for s in samples}):
        kept = [s for s in samples if s.confidence >= threshold]
        if kept and sum(not s.correct for s in kept) / len(kept) <= target_error:
            return threshold
    return 1.0


def low_confidence_fields(confidence: dict[str, float], threshold: float) -> list[str]:
    return [field for field, score in confidence.items() if score < threshold]


def accuracy_report(records: list[dict]) -> dict[tuple[str, str], dict]:
    """Accuracy by (doc_type, field). ``records``: list of {doc_type, field, correct}.
    Surfaces segment-level failures the aggregate hides."""
    agg: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])  # [correct, total]
    for r in records:
        cell = agg[(r["doc_type"], r["field"])]
        cell[1] += 1
        cell[0] += int(bool(r["correct"]))
    return {key: {"accuracy": c / n, "n": n} for key, (c, n) in agg.items()}


def worst_segments(report: dict[tuple[str, str], dict], *, max_accuracy: float = 0.95) -> list:
    """Segments below the accuracy floor — where reviewer capacity should go first."""
    return sorted((seg for seg, m in report.items() if m["accuracy"] < max_accuracy),
                  key=lambda seg: report[seg]["accuracy"])
