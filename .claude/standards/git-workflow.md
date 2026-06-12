# Git & PR workflow

- Branch per story: `feature/SA-<n>-<slug>` off `main`.
- Conventional commits: `feat(SA-<n>): …`, `fix(SA-<n>): …`, `chore: …`,
  `refactor(SA-<n>): …`.
- Every story adds tests; **all tests must pass** before a PR is marked ready.
- Open a PR to `main` with: scope, acceptance-criteria → test mapping, how-to-run,
  and reviewer focus areas. An independent review must pass before merge.
- Definition of Done: ACs checked, tests pass, independent review PASS, Jira story
  transitioned to Done with a closing comment.
