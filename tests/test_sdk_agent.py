"""Unit tests for the Agent SDK harness — no network, no SDK install required.

The SDK owns the loop, so a fake *runner* (async stream of fake messages) stands
in for ``claude_agent_sdk.query``. Tests assert on what the harness surfaces:
final text, cumulative usage, turn count, and that termination is driven by
ResultMessage rather than by parsing assistant prose. Coroutines are driven with
asyncio.run() so no pytest-asyncio dependency is needed.
"""
from __future__ import annotations

import asyncio

from agent.sdk_agent import run_support_agent


# --- fake SDK messages (duck-typed; class names matter to the harness) -------


class _Text:
    def __init__(self, text: str):
        self.text = text


class AssistantMessage:
    def __init__(self, text: str):
        self.content = [_Text(text)]
        self.model = "fake"


class ResultMessage:
    def __init__(
        self,
        *,
        result: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        num_turns: int = 0,
        is_error: bool = False,
        total_cost_usd: float = 0.0,
    ):
        self.result = result
        self.usage = {"input_tokens": input_tokens, "output_tokens": output_tokens}
        self.num_turns = num_turns
        self.is_error = is_error
        self.total_cost_usd = total_cost_usd


def runner_yielding(messages):
    async def _runner(*, prompt, options):
        for message in messages:
            yield message

    return _runner


def run(messages):
    return asyncio.run(
        run_support_agent("a support request", options=None, runner=runner_yielding(messages))
    )


# --- tests ------------------------------------------------------------------


def test_run_returns_final_text():
    result = run([AssistantMessage("Hello"), ResultMessage(result="Hello, resolved.")])
    assert result.text == "Hello, resolved."
    assert result.is_error is False


def test_tool_result_visible_to_model_next_turn():
    """A later turn's answer reflects an earlier tool lookup -> surfaced by the run."""
    result = run(
        [
            AssistantMessage("looking that up"),
            AssistantMessage("The account balance is 42"),
            ResultMessage(result="The account balance is 42"),
        ]
    )
    assert "42" in result.text


def test_cumulative_usage_aggregated_from_messages():
    result = run([ResultMessage(input_tokens=100, output_tokens=50)])
    assert result.input_tokens == 100
    assert result.output_tokens == 50
    assert result.total_tokens == 150


def test_max_turns_is_the_cap():
    """SDK stops at max_turns and reports it -> harness surfaces the capped/error run."""
    result = run(
        [
            AssistantMessage("turn 1"),
            AssistantMessage("turn 2"),
            AssistantMessage("turn 3"),
            ResultMessage(result="", num_turns=3, is_error=True),
        ]
    )
    assert result.num_turns == 3
    assert result.is_error is True


def test_result_message_drives_termination():
    """Final text comes from ResultMessage, never from parsing assistant prose."""
    result = run([AssistantMessage("I am done now"), ResultMessage(result="final answer")])
    assert result.text == "final answer"
    assert result.text != "I am done now"
