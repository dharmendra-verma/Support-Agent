"""Evaluation harness for ResolveDesk (SA-30).

A scripted scenario suite + customer simulator runs the agent end-to-end and produces the
metrics that Week-4 iteration depends on: first-contact-resolution rate, correct-escalation
rate (both directions), tool-routing accuracy, and extraction accuracy by document type and
field. An independent LLM-as-judge (no generation context) scores resolution quality against
an explicit rubric. Results render as JSON + a markdown report.
"""
