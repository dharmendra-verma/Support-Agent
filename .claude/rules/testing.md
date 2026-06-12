---
description: Test-writing conventions; loads only when editing test files.
paths:
  - "**/test_*.py"
  - "tests/**"
---

# Testing rules (path-scoped → test files)

- **Offline always.** Tests must not hit the network or require `ANTHROPIC_API_KEY`.
  Inject fakes: a `FakeClient` for the reference loop, a fake `runner` (async stream
  of fake messages) for the SDK harness.
- **No `pytest-asyncio` markers.** Drive coroutines with `asyncio.run(...)` so the
  suite stays dependency-light.
- One behavior per test; name it for the behavior (`test_terminates_on_end_turn`),
  not the function under test.
- For every termination/branch path, add a test — including the negative case
  (e.g. prose says "done" but `stop_reason != end_turn` ⇒ must NOT terminate).
- Assert on observable outcomes (returned text, accumulated usage, call count), not
  on internal attributes the production code doesn't expose.
- Keep shared test doubles in one place; don't redefine the same fake in two files.
