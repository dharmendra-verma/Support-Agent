"""The agentic loop — **direct Messages-API reference implementation**.

Production agentic work runs through the Claude Agent SDK (``sdk_agent.py``),
which owns its own loop. This module is the hand-rolled equivalent built straight
on the ``anthropic`` Messages API, kept to demonstrate and test the raw
stop_reason control flow the exam covers (D1 TS 1.1) — and as the pattern we fall
back to for any non-SDK, direct-API call.

Control flow is driven *only* by the API ``stop_reason`` — never by parsing the
model's prose. This is the central anti-pattern guard for SA-8:

  while stop_reason == "tool_use":   # keep going: model wants a tool
      run every tool_use block, append all tool_result blocks, re-send
  stop_reason == "end_turn":         # the ONLY normal terminal state
  stop_reason == "max_tokens":       # explicit edge case (raise / surface)

The iteration cap is a *logged safety net*, not a primary stop condition.

SA-8 scaffold: structure is final; the marked body is implemented during the story.
"""
from __future__ import annotations

import logging

from .client import MessagesClient, Usage
from .tools import ToolRegistry

logger = logging.getLogger("resolvedesk.loop")


class MaxTokensError(RuntimeError):
    """Raised when a turn stops on ``max_tokens`` before resolution."""


class IterationCapError(RuntimeError):
    """Safety-net trip: loop exceeded its configured iteration cap."""


def run_agent(
    *,
    client: MessagesClient,
    registry: ToolRegistry,
    user_message: str,
    system: str | None = None,
    usage: Usage | None = None,
    max_iterations: int = 25,
) -> tuple[str, Usage]:
    """Drive the conversation to ``end_turn`` and return (final_text, usage).

    Implementation outline (SA-8):
      1. messages = [{"role": "user", "content": user_message}]; usage = usage or Usage()
      2. for i in range(max_iterations):
           resp = client.create(messages=messages, tools=registry.schemas(), system=system)
           accumulate resp.usage into `usage`
           append {"role": "assistant", "content": resp.content} to messages
           if resp.stop_reason == "end_turn": return concatenated text, usage
           if resp.stop_reason == "max_tokens": raise MaxTokensError
           if resp.stop_reason == "tool_use":
               for every tool_use block: dispatch via registry, collect tool_result
               append ONE user message whose content is all tool_result blocks
               continue   # tool results are now visible on the next create()
      3. logger.error(...); raise IterationCapError  # safety net only
    """
    raise NotImplementedError("SA-8: implement per the outline above")
