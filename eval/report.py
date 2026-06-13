"""Render evaluation results as JSON + a markdown report (SA-30)."""
from __future__ import annotations

import json

from .harness import Metrics


def metrics_to_dict(metrics: Metrics, judge_summary: dict | None = None) -> dict:
    """Serialise metrics (+ optional judge summary) to a plain dict for JSON output."""
    out = {
        "total": metrics.total,
        "first_contact_resolution_rate": round(metrics.fcr_rate, 3),
        "escalation": {
            "correct_rate": round(metrics.correct_escalation_rate, 3),
            "missed_rate": round(metrics.missed_escalation_rate, 3),
            "false_rate": round(metrics.false_escalation_rate, 3),
            "tp": metrics.escalation_tp, "fp": metrics.escalation_fp,
            "fn": metrics.escalation_fn, "tn": metrics.escalation_tn,
        },
        "tool_routing_accuracy": round(metrics.tool_routing_accuracy, 3),
        "extraction_accuracy": {f"{dt}.{fld}": round(m["accuracy"], 3)
                                for (dt, fld), m in metrics.extraction_accuracy.items()},
        "by_category": {k: {kk: round(vv, 3) if isinstance(vv, float) else vv
                            for kk, vv in v.items()}
                        for k, v in metrics.by_category.items()},
    }
    if judge_summary is not None:
        out["judge"] = {
            "n": judge_summary["n"],
            "overall_pass_rate": round(judge_summary["overall_pass_rate"], 3),
            "mean_score": round(judge_summary["mean_score"], 3),
            "by_criterion": {k: round(v, 3) for k, v in judge_summary["by_criterion"].items()},
        }
    return out


def to_json(metrics: Metrics, judge_summary: dict | None = None) -> str:
    return json.dumps(metrics_to_dict(metrics, judge_summary), indent=2, sort_keys=True)


def render_markdown(metrics: Metrics, judge_summary: dict | None = None, *,
                    fcr_target: float = 0.80) -> str:
    """A readable report: headline metrics (with the FCR target call-out), the escalation
    confusion matrix in both directions, tool routing, extraction worst-segments, and the
    independent-judge summary."""
    fcr = metrics.fcr_rate
    status = "✅ meets" if fcr >= fcr_target else "❌ below"
    lines = [
        "# Evaluation report",
        "",
        f"- **First-contact resolution:** {fcr:.0%} ({status} {fcr_target:.0%} target)",
        f"- **Correct-escalation rate:** {metrics.correct_escalation_rate:.0%} "
        f"(missed {metrics.missed_escalation_rate:.0%}, false {metrics.false_escalation_rate:.0%})",
        f"- **Tool-routing accuracy:** {metrics.tool_routing_accuracy:.0%}",
        f"- **Scenarios:** {metrics.total}",
        "",
        "## Escalation confusion matrix",
        "| | escalated | not escalated |",
        "| --- | --- | --- |",
        f"| **should escalate** | {metrics.escalation_tp} (tp) | {metrics.escalation_fn} (fn, missed) |",
        f"| **should not** | {metrics.escalation_fp} (fp, over) | {metrics.escalation_tn} (tn) |",
        "",
        "## By category",
        "| category | n | resolution✓ | escalation✓ |",
        "| --- | --- | --- | --- |",
    ]
    for cat, m in sorted(metrics.by_category.items()):
        lines.append(f"| {cat} | {m['n']} | {m['resolution_correct']:.0%} "
                     f"| {m['escalation_correct']:.0%} |")

    if metrics.extraction_accuracy:
        lines += ["", "## Extraction accuracy (worst segments first)",
                  "| doc_type.field | accuracy | n |", "| --- | --- | --- |"]
        # Sort ALL segments ascending by accuracy so the table genuinely leads with the worst —
        # never fall back to insertion order, which would contradict the heading.
        ordered = sorted(metrics.extraction_accuracy.items(), key=lambda kv: kv[1]["accuracy"])
        for (dt, fld), m in ordered:
            lines.append(f"| {dt}.{fld} | {m['accuracy']:.0%} | {m['n']} |")

    if judge_summary is not None:
        lines += ["", "## Independent judge (rubric, no generation context)",
                  f"- **Overall pass rate:** {judge_summary['overall_pass_rate']:.0%}",
                  # mean_score is a normalised 0-1 fraction of criteria passed (see
                  # RubricScore.score), so a percentage render is correct.
                  f"- **Mean rubric pass fraction:** {judge_summary['mean_score']:.0%}", "",
                  "| criterion | pass rate |", "| --- | --- |"]
        for k, v in judge_summary["by_criterion"].items():
            lines.append(f"| {k} | {v:.0%} |")
    return "\n".join(lines)
