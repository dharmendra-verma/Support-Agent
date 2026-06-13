# Tool distribution & tool_choice (SA-13)

Exam: D2 TS 2.3. Two levers keep tool selection reliable as the system grows.

## 1. Give each agent only its role's tools
Selection accuracy degrades with tool count — **~4–5 tools per agent is the sweet spot;
~18 starts failing.** `tooling.ROLE_TOOLS` scopes each role (all ≤5):

| Role | Tools |
|---|---|
| verification | `get_customer` |
| status | `check_refund_status` |
| triage | `get_customer`, `lookup_order`, `check_refund_status` |
| refunds | `get_customer`, `lookup_order`, `process_refund`, `escalate_to_human` |

### Routing experiment (5 vs 15+ tools)
With a live key, send the SA-10 ambiguous prompts twice: once with the role's 4–5 tools,
once with the same tools padded to 15+ decoys. Expectation (and the documented finding):
the small set routes ≥9/10; the bloated set drops materially. Procedure mirrors
`tests/test_tool_routing.py::test_get_customer_vs_lookup_order_routing` (skipped without
`ANTHROPIC_API_KEY`). Record the two accuracies here as evidence.

## 2. `tool_choice` per workflow step
| Builder | API shape | Use when |
|---|---|---|
| `auto()` | `{"type":"auto"}` | model may act or explain |
| `any_tool()` | `{"type":"any"}` | a text-only reply is never acceptable — must call *some* tool |
| `force(name)` | `{"type":"tool","name":name}` | a specific tool must run next (e.g. verification) |
| `none()` | `{"type":"none"}` | no tool may be called |

**Forced selection only governs the *next* response.** A constrained flow therefore chains
one turn per step — `tooling.refund_workflow_steps()`:
1. `force("get_customer")` + only the verification tool → **verification is guaranteed first**
2. `any_tool()` → must find the order (no chit-chat)
3. `auto()` → may act or explain the outcome

## 3. Scoped narrow tool
`check_refund_status` returns *only* the status for the high-frequency "where's my order?"
need — selected more reliably (and cheaper) than the general `lookup_order`, which returns
the full order. It delegates to `lookup_order`, so it inherits SA-11 validation/error
handling and never masks a failure as an empty result.
