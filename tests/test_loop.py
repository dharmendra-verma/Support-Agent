"""Unit tests for the agentic loop — no network; a FakeClient scripts responses.

Covers every termination path in the SA-8 acceptance criteria. Tests are written
first (TDD) and currently xfail against the scaffold until loop.py is implemented.
"""
from __future__ import annotations

import pytest

# Implementation lands during SA-8; importing is fine, calling raises NotImplementedError.
from agent.loop import run_agent  # noqa: F401


pytestmark = pytest.mark.xfail(reason="SA-8 loop not yet implemented", strict=False)


def test_terminates_on_end_turn():
    """A response with stop_reason=end_turn ends the loop and returns its text."""
    raise NotImplementedError


def test_continues_on_tool_use_then_ends():
    """tool_use -> dispatch -> append tool_result -> re-send -> end_turn."""
    raise NotImplementedError


def test_tool_result_is_visible_next_iteration():
    """Answer depends on a prior tool result, proving context accumulation (key AC)."""
    raise NotImplementedError


def test_parallel_tool_use_blocks_all_handled():
    """Multiple tool_use blocks in one response -> all executed, all results returned."""
    raise NotImplementedError


def test_max_tokens_raises():
    """stop_reason=max_tokens is an explicit edge case, not a silent stop."""
    raise NotImplementedError


def test_iteration_cap_is_safety_net():
    """A misbehaving model that never ends trips the logged cap, not an infinite loop."""
    raise NotImplementedError


def test_cumulative_usage_tracked():
    """input/output tokens accumulate across every turn in the conversation."""
    raise NotImplementedError
