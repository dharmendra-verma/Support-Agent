# Multi-issue session decomposition (SA-29)

Customers raise several concerns in one message ("refund my order, fix my billing, and update
my address"). One blob drops items; serial handling is slow. SA-29 decomposes the message into
distinct tracked `Issue` items, investigates independent ones in parallel under a shared
verified-customer context, and synthesises one unified response with **no item dropped**.
Exam: D1 TS 1.4, D5 TS 5.1. Code: `src/agent/decompose.py`. Tests: `tests/test_multi_issue.py`.

## Decomposition

`decompose_message(text)` splits on concern boundaries (commas/semicolons/sentences + listing
conjunctions; a `.` is a delimiter only as a sentence terminator, **never** a decimal inside
`$49.99`). Each clause with a recognisable intent (refund, billing, address, cancel,
order_status, return, account) becomes one `Issue` whose **own** case-facts layer (SA-28) holds
that clause's order IDs / amounts / statuses — so the refund item owns the order and amount and
the address item does not inherit them.

## Dependencies + sequencing

Some kinds can't be actioned until another resolves: a **refund depends on the order's
status/cancellation**. `_link_dependencies` wires `depends_on` from the kind rules, and
`sequence(issues)` topologically layers them — independent items share a layer (run in
parallel), a dependent item lands in a strictly later layer, and a dependency cycle raises
rather than looping.

## Parallel investigation + synthesis

`investigate(issues, investigate_fn=…, customer=…)` runs each layer's items **concurrently**
(`asyncio.gather`) under the shared verified-`customer` context; a dependent item receives the
prior results it waits on. `IssueLedger` tracks per-issue status as a separate context layer.
`synthesize_response` merges results into one reply where **every** issue appears — an
unresolved one is shown "still pending", never dropped.

## No-drop guarantee

`test_no_item_dropped_across_ten_multi_concern_cases` runs 10 varied multi-concern messages and
asserts decomposition count == investigated count == items in the unified response for each.

## How to run

```bash
PYTHONPATH=src python -m pytest tests/test_multi_issue.py -q
```
