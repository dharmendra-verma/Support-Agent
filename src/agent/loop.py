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
from typing import Any

from .client import MessagesClient, Usage
from .tools import ToolRegistry

logger = logging.getLogger("resolvedesk.loop")


class MaxTokensError(RuntimeError):
    """Raised when a turn stops on ``max_tokens`` before resolution."""


class IterationCapError(RuntimeError):
    """Safety-net trip: loop exceeded its configured iteration cap."""


class UnknownToolError(RuntimeError):
    """The model requested a tool that is not in the registry (config/registry drift)."""


def _text_of(content: Any) -> str:
    """Concatenate the text blocks of an assistant response."""
    parts = [
        getattr(block, "text", "")
        for block in content
        if getattr(block, "type", None) == "text"
    ]
    return "".join(parts)


def run_agent(
    *,
    client: MessagesClient,
    registry: ToolRegistry,
    user_message: str,
    system: str | None = None,
    usage: Usage | None = None,
    max_iterations: int = 25,
) -> tuple[str, Usage]:
    """Drive the conversation to ``end_turn`` and return ``(final_text, usage)``.

    Control flow dispatches solely on ``stop_reason``. The model's prose is never
    inspected to decide whether to stop; ``max_iterations`` is a logged safety net.
    """
    usage = usage or Usage()
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]
    tool_schemas = registry.schemas()  # immutable for the run; build once

    for _ in range(max_iterations):
        resp = client.create(messages=messages, tools=tool_schemas, system=system)

        # Cumulative token usage per conversation (authoritative tally).
        turn_usage = getattr(resp, "usage", None)
        if turn_usage is not None:
            usage.add(
                getattr(turn_usage, "input_tokens", 0) or 0,
                getattr(turn_usage, "output_tokens", 0) or 0,
            )

        # Echo the assistant turn back into history before acting on it.
        messages.append({"role": "assistant", "content": resp.content})

        stop_reason = getattr(resp, "stop_reason", None)

        if stop_reason == "end_turn":
            return _text_of(resp.content), usage

        if stop_reason == "max_tokens":
            # Explicit edge case: the turn was truncated, not completed.
            raise MaxTokensError("response stopped on max_tokens before resolution")

        if stop_reason == "tool_use":
            # Handle EVERY tool_use block (responses may carry several in parallel)
            # and return ALL results in a single user message so they are visible
            # to the model on the next iteration.
            tool_results: list[dict[str, Any]] = []
            for block in resp.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                if block.name not in registry:
                    # Registry/config drift is a programming bug — fail fast rather
                    # than feeding a fabricated error back to the model and burning
                    # iterations up to the safety-net cap.
                    raise UnknownToolError(f"model requested unregistered tool: {block.name!r}")
                result_block: dict[str, Any] = {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                }
                try:
                    result_block["content"] = registry.dispatch(block.name, block.input)
                except Exception as exc:  # genuine tool runtime failure -> surface to model
                    result_block["content"] = f"error: {exc}"
                    result_block["is_error"] = True
                tool_results.append(result_block)
            messages.append({"role": "user", "content": tool_results})
            continue

        # Any other stop_reason (e.g. "stop_sequence"): treat as terminal, no parsing.
        return _text_of(resp.content), usage

    logger.error("agent hit max_iterations=%d safety net without end_turn", max_iterations)
    raise IterationCapError(f"exceeded max_iterations={max_iterations} without end_turn")
