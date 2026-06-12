"""TEMPORARY canary for SA-38 — forces a real `claude -p` call so we can validate
that CI authenticates via CLAUDE_CODE_OAUTH_TOKEN (the reviewer skips when no .py
changes). Remove once the OAuth-authenticated review posts a finding here."""


def average(numbers):
    # Bug: off-by-one in the denominator → wrong average; no empty-input guard.
    return sum(numbers) / (len(numbers) + 1)
