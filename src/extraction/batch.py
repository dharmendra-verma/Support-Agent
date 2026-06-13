"""Batch extraction over a historical backlog via the Message Batches API (SA-19).

Batch is the right tool for 10k overnight extractions: ~half the cost, non-blocking, no
latency requirement. Each document becomes one request with a stable ``custom_id`` so
results (returned out of order) can be correlated on retrieval. Failed items are resubmitted
**by custom_id only**, with modifications (e.g. chunking an oversized document).

Batch requests are **pure extraction** — a single user turn, no multi-turn tool calling.
The live submit/poll/results calls take an injected ``client``; request-building, correlation,
failure classification, chunking, and the SLA math are all pure and unit-tested.
"""
from __future__ import annotations

import math
from typing import Any

from extraction.extractor import NORMALIZATION_PROMPT, parse_extraction, tool_choice
from extraction.schemas import tool_defs


def build_request(custom_id: str, document: str, *, doc_type: str | None = None,
                  model: str = "claude-sonnet-4-6", max_tokens: int = 1024) -> dict:
    """One batch request: pure extraction (single user message), correlated by custom_id."""
    return {
        "custom_id": custom_id,
        "params": {
            "model": model,
            "max_tokens": max_tokens,
            "system": NORMALIZATION_PROMPT,
            "tools": tool_defs(),
            "tool_choice": tool_choice(doc_type),
            "messages": [{"role": "user", "content": document}],
        },
    }


def build_batch_requests(docs: list[dict]) -> list[dict]:
    """``docs``: list of {custom_id, document, doc_type?}."""
    return [build_request(d["custom_id"], d["document"], doc_type=d.get("doc_type")) for d in docs]


def submit(requests: list[dict], *, client: Any = None) -> Any:
    if client is None:
        import anthropic

        client = anthropic.Anthropic()
    return client.messages.batches.create(requests=requests)


def is_ended(batch: Any) -> bool:
    return getattr(batch, "processing_status", None) == "ended"


def correlate_results(results: Any, *, doc_types: dict[str, str] | None = None) -> dict[str, dict]:
    """Map custom_id -> {status, extraction|error}. Succeeded results are parsed via the
    SA-17 tool_use parser; everything else records its failure status."""
    doc_types = doc_types or {}
    out: dict[str, dict] = {}
    for r in results:
        cid = r.custom_id
        result = r.result
        status = getattr(result, "type", None)
        if status == "succeeded":
            try:
                extraction = parse_extraction(result.message, doc_types.get(cid))
                out[cid] = {"status": "succeeded", "extraction": extraction}
            except (ValueError, KeyError) as exc:
                out[cid] = {"status": "parse_error", "error": str(exc)}
        else:
            out[cid] = {"status": status or "errored",
                        "error": getattr(getattr(result, "error", None), "message", str(status))}
    return out


def failed_ids(correlated: dict[str, dict]) -> list[str]:
    return [cid for cid, r in correlated.items() if r["status"] != "succeeded"]


def chunk_document(document: str, max_chars: int) -> list[str]:
    return [document[i:i + max_chars] for i in range(0, len(document), max_chars)] or [""]


def resubmit_requests(failed: list[str], docs_by_id: dict[str, dict], *,
                      max_chars: int | None = None) -> list[dict]:
    """Rebuild requests for failed custom_ids; an oversized doc is split into
    ``<custom_id>::chunkN`` requests so each fits the model's window."""
    reqs = []
    for cid in failed:
        doc = docs_by_id[cid]
        text = doc["document"]
        if max_chars and len(text) > max_chars:
            for j, chunk in enumerate(chunk_document(text, max_chars)):
                reqs.append(build_request(f"{cid}::chunk{j}", chunk, doc_type=doc.get("doc_type")))
        else:
            reqs.append(build_request(cid, text, doc_type=doc.get("doc_type")))
    return reqs


def submission_cadence(total_docs: int, max_batch_size: int = 100_000,
                       processing_window_h: int = 24, target_turnaround_h: int = 30) -> dict:
    """SLA math: to guarantee ``target_turnaround_h``, every batch must clear the
    ``processing_window_h`` ceiling with ``target - window`` hours of slack left for one
    resubmission of failures. Returns the plan."""
    n_batches = math.ceil(total_docs / max_batch_size)
    slack_h = target_turnaround_h - processing_window_h
    return {
        "batches": n_batches,
        "slack_hours_for_resubmission": slack_h,
        "submit_each_batch_at_least_h_before_deadline": processing_window_h,
        "feasible": slack_h >= 0,
    }
