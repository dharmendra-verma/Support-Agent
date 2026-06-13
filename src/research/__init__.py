"""Multi-agent research orchestration (SA-21).

A *coordinator* agent decomposes a research question into non-overlapping subtasks and
spawns role-scoped *subagents* in parallel via the Agent SDK ``Task`` tool, then synthesises
their findings. Subagents share NO context with the coordinator or each other — every
subtask prompt is self-contained.
"""
