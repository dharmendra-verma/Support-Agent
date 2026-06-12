"""Unit tests for the direct-API reference loop — no network; a FakeClient scripts
responses. Covers every termination path in the SA-8 acceptance criteria.
"""
from __future__ import annotations

import pytest

from agent.loop import IterationCapError, MaxTokensError, run_agent
from agent.tools import Tool, ToolRegistry


# --- test doubles -----------------------------------------------------------


class Block:
    """A content block (text or tool_use) with attribute access like the SDK's."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def text(t: str) -> Block:
    return Block(type="text", text=t)


def tool_use(id: str, name: str, input: dict) -> Block:
    return Block(type="tool_use", id=id, name=name, input=input)


class Usage:
    def __init__(self, input_tokens: int, output_tokens: int):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class Resp:
    def __init__(self, stop_reason, content, usage=None):
        self.stop_reason = stop_reason
        self.content = content
        self.usage = usage or Usage(0, 0)


class FakeClient:
    """Returns scripted responses and records every create() call."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, *, messages, tools, system=None):
        # Deep-ish copy of message roles/content refs so we can inspect history.
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        return self._responses.pop(0)


class AlwaysToolUseClient:
    """Never emits end_turn — used to prove the iteration-cap safety net."""

    def __init__(self):
        self.calls = 0

    def create(self, *, messages, tools, system=None):
        self.calls += 1
        return Resp("tool_use", [tool_use(f"t{self.calls}", "noop", {})], Usage(1, 1))


def registry_with(name="lookup", output="OK") -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(
        Tool(
            name=name,
            description="test tool",
            input_schema={"type": "object", "properties": {}},
            handler=lambda _inp: output,
        )
    )
    return reg


# --- tests ------------------------------------------------------------------


def test_terminates_on_end_turn():
    client = FakeClient([Resp("end_turn", [text("Resolved.")], Usage(10, 5))])
    out, usage = run_agent(client=client, registry=ToolRegistry(), user_message="hi")
    assert out == "Resolved."
    assert usage.total_tokens == 15
    assert len(client.calls) == 1


def test_continues_on_tool_use_then_ends():
    client = FakeClient(
        [
            Resp("tool_use", [tool_use("t1", "lookup", {})], Usage(10, 5)),
            Resp("end_turn", [text("done")], Usage(8, 4)),
        ]
    )
    out, _ = run_agent(client=client, registry=registry_with(), user_message="hi")
    assert out == "done"
    # Second call must carry the tool_result for t1 in a user message.
    second = client.calls[1]["messages"][-1]
    assert second["role"] == "user"
    assert second["content"][0]["type"] == "tool_result"
    assert second["content"][0]["tool_use_id"] == "t1"


def test_tool_result_is_visible_next_iteration():
    """The answer depends on a prior tool result -> it must reach the next request."""
    client = FakeClient(
        [
            Resp("tool_use", [tool_use("t1", "lookup", {})], Usage(1, 1)),
            Resp("end_turn", [text("the sky is blue")], Usage(1, 1)),
        ]
    )
    run_agent(client=client, registry=registry_with(output="blue"), user_message="color?")
    tool_result = client.calls[1]["messages"][-1]["content"][0]
    assert tool_result["content"] == "blue"  # the tool's output is visible on re-send


def test_parallel_tool_use_blocks_all_handled():
    client = FakeClient(
        [
            Resp(
                "tool_use",
                [tool_use("t1", "lookup", {}), tool_use("t2", "lookup", {})],
                Usage(1, 1),
            ),
            Resp("end_turn", [text("both done")], Usage(1, 1)),
        ]
    )
    run_agent(client=client, registry=registry_with(), user_message="hi")
    results = client.calls[1]["messages"][-1]["content"]
    ids = {r["tool_use_id"] for r in results}
    assert ids == {"t1", "t2"}  # every parallel block returned a result


def test_max_tokens_raises():
    client = FakeClient([Resp("max_tokens", [text("truncat")], Usage(1, 1))])
    with pytest.raises(MaxTokensError):
        run_agent(client=client, registry=ToolRegistry(), user_message="hi")


def test_iteration_cap_is_safety_net():
    client = AlwaysToolUseClient()
    with pytest.raises(IterationCapError):
        run_agent(
            client=client,
            registry=registry_with(name="noop"),
            user_message="hi",
            max_iterations=3,
        )
    assert client.calls == 3  # capped, not infinite


def test_cumulative_usage_tracked():
    client = FakeClient(
        [
            Resp("tool_use", [tool_use("t1", "lookup", {})], Usage(10, 5)),
            Resp("end_turn", [text("done")], Usage(8, 4)),
        ]
    )
    _, usage = run_agent(client=client, registry=registry_with(), user_message="hi")
    assert usage.input_tokens == 18
    assert usage.output_tokens == 9
    assert usage.total_tokens == 27
