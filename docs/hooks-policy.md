# Policy & normalization hooks — A/B study notes (SA-15)

Exam principle (D1 TS 1.5): enforce policy and shape tool I/O with **hooks**, not prompt
instructions. Two hooks in `src/agent/hooks.py`:

## PreToolUse — refund-threshold interception
Blocks `process_refund` above the $500 autonomous limit and redirects to `escalate_to_human`.
Because it runs in the dispatch layer *before* the tool, the money-moving handler is never
reached — `tests/test_hooks.py::test_30_run_threshold_blocks_100_percent` proves **0 leaks
across 30 attempts** with no model in the loop.

### A/B: prompt-only vs hook
| | Prompt-only ("never refund over $500") | PreToolUse hook |
|---|---|---|
| Guarantee | probabilistic — non-zero leak rate | deterministic — 0 over-limit refunds |
| Failure mode | model refunds $600 "because the customer was upset" | impossible — call is denied before execution |
| 30-run result | some leaks (sampled) | **0/30** (proven) |

This supersedes SA-10's soft `requires_approval` (a tool *return value* the model could
ignore) with a hard pre-execution block, and complements SA-14's verification gate.

## PostToolUse — lossless normalization
Backends return heterogeneous formats (Unix epochs vs ISO 8601, numeric vs variant status
codes). The hook normalizes results **before the model sees them**:
- timestamps → ISO 8601 UTC (`TIMESTAMP_FIELDS`)
- status codes → canonical strings (`CANONICAL_STATUS`, e.g. `2`/`"SHIP"` → `"shipped"`)

**Lossless:** originals are preserved under a `raw` key on each normalized record, so nothing
is destroyed — the model reasons over clean values while the audit trail keeps the source.

## SDK wiring
`build_hooks_config()` maps these to `ClaudeAgentOptions(hooks=...)` via `HookMatcher`
(PreToolUse matched to `process_refund`, PostToolUse for all tools). Lazy-imported (the SDK
isn't installed in CI); the decision/normalization logic itself is fully unit-tested.
