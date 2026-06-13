# Backlog batch strategy (SA-19)

Exam: D4 TS 4.5. 10,000 historical tickets need extraction for analytics — the canonical
**batch** workload: non-blocking, overnight, no latency requirement, ~half the per-token cost.

## Why batch here but synchronous for live support (decision note)
| | Live support flow | Historical backlog |
|---|---|---|
| Latency | a customer is waiting → must be **synchronous/blocking** | nobody waits → async is fine |
| Pattern | multi-turn **tool calling** (verify → look up → refund) | single-shot **extraction**, no tools-loop |
| Cost | pay for immediacy | batch ≈ 50% cheaper |
| API | Messages API (sync) | **Message Batches API** |

The two never mix: batch requests are *pure extraction* (one user turn, no multi-turn tool
calling), so the agent loop stays on the synchronous API.

## custom_id correlation
Every request carries a stable `custom_id` (the ticket id). Results return **out of order**;
`batch.correlate_results` maps each result back to its `custom_id`, parsing succeeded ones via
the SA-17 tool_use parser and recording failures.

## Failure resubmission
`batch.resubmit_requests(failed, docs_by_id, max_chars=...)` rebuilds requests for the failed
custom_ids only. Oversized documents are split into `<custom_id>::chunkN` requests so each
fits the context window — modify-and-resubmit, never re-run the whole batch.

## Prompt refinement before the full run
Submit a **50-document sample first**, measure first-pass success, refine the extraction
prompt/few-shot (SA-18) on the failures, *then* submit the full 10k. `scripts/run_backlog.py
--sample 50` prints the first-pass rate. Record it here before the full run.

## SLA math (30-hour turnaround, 24-hour window)
The Batches API guarantees completion within a **24-hour** processing window. To promise a
**30-hour** end-to-end turnaround:
- `slack = 30 − 24 = 6 hours` of buffer — enough for **one** resubmission of failures (a
  resubmitted chunked batch also clears within its own 24h, but the 6h slack covers the
  correlate-and-resubmit turnaround, not a second full window).
- Therefore submit each batch **≥ 24 hours before its deadline**, and start the run so the
  6-hour slack remains for the resubmission pass.
- `batch.submission_cadence(total, max_batch_size)` returns the batch count + this plan
  (`feasible` is false if `target < window`). At 10k docs (well under the 100k/batch cap)
  it's a single batch + one resubmission, comfortably inside 30h.
