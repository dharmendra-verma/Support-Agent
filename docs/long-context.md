# Long-conversation context layer (SA-28)

Long support conversations fail three ways: **progressive summarization** blurs exact figures
("about $50"), the **lost-in-the-middle** effect drops mid-history facts, and a 40-field order
lookup **bloats** context with 5 relevant fields. SA-28 adds a persistent case-facts layer plus
tool-output trimming. Exam: D5 TS 5.1. Code: `src/agent/case_facts.py`, `src/agent/trimming.py`.
Tests: `tests/test_long_context.py`.

## Case-facts block

`CaseFacts` holds the authoritative transactional facts — orders+statuses, amounts, dates,
customer-stated expectations. `update_facts(facts, turn_text)` runs **every turn** (deterministic
regex extractor; inject a single-shot Claude Messages-API extractor via `extract_fn` for
production). The block is rendered by `to_block()` and **prepended to each request, outside the
summarized history**, so exact figures survive however the rest of the history is compressed.

Key properties:
- **Updated in place, not append-only.** `orders` is `order_id -> latest status`; a status
  change *overwrites* the old value, so the block never carries a self-contradictory history.
  Amounts/dates/expectations are de-duplicated on insert.
- **Key facts lead** (`## Orders & statuses` first), countering lost-in-the-middle.

## Tool-output trimming

`trim_output(result, relevant)` projects a tool result to just the relevant keys *before* it
enters context (missing keys skipped, not faked). `trim_savings(before, after)` measures the
reduction (`before_tokens`/`after_tokens`/`saved_tokens`/`pct_saved`) so the saving is evidenced.

## Assembly

`assemble_context(case_facts_block, sections)` puts the case-facts block at the very top, then
each labelled section under an explicit `## header` — key summaries first.

## The 20-turn recall test (failing baseline kept as evidence)

`tests/test_long_context.py` builds a 20+ turn conversation whose **turn 2** states `$49.99`,
`#12345`, `2026-01-02`, then 18 turns of unrelated chatter.

- `test_baseline_without_layer_loses_exact_figure_from_turn_2` — with only summarized history,
  the exact turn-2 figures are **gone** at turn 20 (the failure mode, kept as evidence).
- `test_case_facts_layer_recalls_exact_figure_at_turn_20` — with the layer, `$49.99`, `#12345`,
  and `2026-01-02` are still present verbatim in the assembled context at turn 20.

## How to run

```bash
PYTHONPATH=src python -m pytest tests/test_long_context.py -q
```
