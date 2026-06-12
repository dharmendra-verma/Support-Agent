# Code review criteria (used by humans and the CI reviewer)

The CI reviewer (`claude -p`, see `docs/ci-review.md`) and human reviewers apply these
rules. They are deliberately explicit — **no "be conservative" vagueness**, because false
positives destroy trust in automated review.

## REPORT — always surface these
| Category | Report when… | Example |
|---|---|---|
| `bug` | logic is wrong on a realistic input/state | inverted condition; `if final:` drops a valid empty result; missing `await` |
| `security` | a vuln or unsafe handling of untrusted input/secrets | command injection; secret logged; unsafe deserialization |
| `correctness-test` | a test asserts a tautology or doesn't exercise its claim | "visibility" test that inspects the assembled message, not a result-dependent answer |
| `breaking-change` | a public signature/return shape changes without callers updated | renamed return key still read by a caller |

## SKIP — do not post these (handled by ruff / humans)
| Category | Why skipped |
|---|---|
| `style` | formatting/line-length — ruff owns it |
| `nit` | naming/wording preferences with no behavior change |
| `subjective` | "I'd structure this differently" without a concrete defect |

## Severity (concrete anchors)
- `critical` — data loss, security breach, or CI/prod outage. *e.g. secret committed; refund bypasses the threshold gate.*
- `high` — wrong result on a common path; crash on a reachable input. *e.g. loop never terminates on `end_turn`.*
- `medium` — wrong result on an edge case, or a real maintainability trap. *e.g. empty-result fallback surfaces prose.*
- `low` — minor, non-behavioral; usually SKIP unless trivially fixable.

## Dismissal tracking (anti-false-positive)
Every finding carries a `detected_pattern` (a short stable key for the rule that fired,
e.g. `empty-result-fallback`). When a finding is dismissed, record the pattern so the CI
reviewer can suppress that pattern on re-runs and we can tune noisy rules. Re-runs report
**only new or still-unaddressed** findings — never re-post an already-posted finding.
