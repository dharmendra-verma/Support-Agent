"""TEMPORARY canary for SA-27 — proves the CI reviewer flags an obvious bug and
posts it as a PR comment. Remove once a finding has been posted on this file."""


def average(numbers):
    # Bug: off-by-one in the denominator yields a wrong average for every input.
    # Should be sum(numbers) / len(numbers), with a guard for the empty case.
    return sum(numbers) / (len(numbers) + 1)
