"""Unit tests for the Agent SDK harness — no network; the SDK transport is faked.

The SDK owns the loop, so these tests assert on what it *surfaces*: accumulated
text, cumulative token usage, turn count, and that a later answer depends on an
earlier tool result (context accumulation). The iteration cap is asserted via
max_turns rather than a hand-rolled counter.

Written first (TDD); xfail against the scaffold until sdk_agent.py is implemented.
"""
from __future__ import annotations

import pytest

from agent.sdk_agent import AgentResult, run_support_agent  # noqa: F401


pytestmark = pytest.mark.xfail(reason="SA-8 SDK harness not yet implemented", strict=False)


def test_run_returns_final_text():
    """A simple request resolves and AgentResult.text holds the model's answer."""
    raise NotImplementedError


def test_tool_result_visible_to_model_next_turn():
    """Answer depends on a tool's output from a prior turn (context accumulation AC)."""
    raise NotImplementedError


def test_cumulative_usage_aggregated_from_messages():
    """input/output tokens accumulate across AssistantMessage/ResultMessage usage."""
    raise NotImplementedError


def test_max_turns_is_the_cap():
    """A model that keeps calling tools stops at max_turns — SDK cap, not infinite loop."""
    raise NotImplementedError


def test_result_message_drives_termination():
    """Completion is detected via ResultMessage, never by parsing assistant prose."""
    raise NotImplementedError
