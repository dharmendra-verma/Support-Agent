"""Backlog batch-extraction runner (SA-19).

Workflow:
  1. Refine the prompt on a 50-doc SAMPLE; record first-pass success before the full run.
  2. Submit the full backlog as a batch (custom_id per doc).
  3. Poll until ended; correlate results by custom_id.
  4. Resubmit failures by custom_id (chunking oversized docs).

Live (needs ANTHROPIC_API_KEY). Cost control: --sample caps the batch size for testing.
"""
from __future__ import annotations

import argparse
import time

from extraction import batch


def poll_until_ended(client, batch_id, *, interval_s: int = 30, timeout_s: int = 90_000):
    waited = 0
    while waited < timeout_s:
        b = client.messages.batches.retrieve(batch_id)
        if batch.is_ended(b):
            return b
        time.sleep(interval_s)
        waited += interval_s
    raise TimeoutError(f"batch {batch_id} did not end within {timeout_s}s")


def run(docs: list[dict], *, sample: int | None = None, max_chars: int | None = None):
    import anthropic

    client = anthropic.Anthropic()
    work = docs[:sample] if sample else docs

    submitted = client.messages.batches.create(requests=batch.build_batch_requests(work))
    ended = poll_until_ended(client, submitted.id)
    results = client.messages.batches.results(ended.id)
    correlated = batch.correlate_results(results, doc_types={d["custom_id"]: d.get("doc_type") for d in work})

    failed = batch.failed_ids(correlated)
    first_pass = 1 - len(failed) / max(len(work), 1)
    print(f"first-pass success: {first_pass:.1%} ({len(work) - len(failed)}/{len(work)})")

    if failed:
        docs_by_id = {d["custom_id"]: d for d in work}
        retry_batch = client.messages.batches.create(
            requests=batch.resubmit_requests(failed, docs_by_id, max_chars=max_chars))
        print(f"resubmitted {len(failed)} failed item(s) as batch {retry_batch.id}")
    return correlated


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=50, help="cap batch size (cost control)")
    ap.add_argument("--max-chars", type=int, default=20000, help="chunk docs over this size on retry")
    args = ap.parse_args()
    raise SystemExit("provide a document source; this is a template runner (see docs/batch-strategy.md)")
