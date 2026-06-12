"""Unit tests for the direct-API reference loop — no network; a FakeClient scripts
responses. Covers every termination path in the SA-8 acceptance criteria.
"""
from __future__ import annotations

import pytest

from agent.loop import IterationCapError, MaxTokensError, UnknownToolError, run_agent
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


class EchoToolResultClient:
    """The final answer is DERIVED from the tool_result the loop fed back into
    history — so the test only passes if the prior tool output is genuinely
    visible on the next request (real context accumulation, not a passthrough)."""

    def __init__(self):
        self.calls = 0

    def create(self, *, messages, tools, system=None):
        self.calls += 1
        for message in messages:
            content = message.get("content")
            if message["role"] == "user" and isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        # Answer depends on what the tool returned last turn.
                        return Resp(
                            "end_turn",
                            [text(f"the answer is {block['content']}")],
                            Usage(1, 1),
                        )
        return Resp("tool_use", [tool_use("t1", "lookup", {})], Usage(1, 1))


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
    """The final answer is computed FROM a prior tool result (real visibility)."""
    client = EchoToolResultClient()
    out, _ = run_agent(client=client, registry=registry_with(output="42"), user_message="q")
    assert out == "the answer is 42"  # answer depends on the tool's output
    assert client.calls == 2  # tool turn, then the answer derived from its result


def test_does_not_parse_prose_to_terminate():
    """Prose saying 'done' while stop_reason==tool_use must NOT end the loop.

    Guards the central SA-8 anti-pattern: termination is driven by stop_reason
    alone. A regression like `if "done" in text: return` would terminate on the
    first turn (1 call, wrong answer) and fail this test.
    """
    client = FakeClient(
        [
            Resp(
                "tool_use",
                [text("All done! I have finished."), tool_use("t1", "lookup", {})],
                Usage(1, 1),
            ),
            Resp("end_turn", [text("real answer")], Usage(1, 1)),
        ]
    )
    out, _ = run_agent(client=client, registry=registry_with(), user_message="q")
    assert out == "real answer"
    assert len(client.calls) == 2  # continued past the 'done' prose


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


def test_unknown_tool_fails_fast():
    """A tool_use for an unregistered tool raises immediately, not a silent loop."""
    client = FakeClient([Resp("tool_use", [tool_use("t1", "ghost", {})], Usage(1, 1))])
    with pytest.raises(UnknownToolError):
        run_agent(client=client, registry=registry_with(name="lookup"), user_message="q")
    assert len(client.calls) == 1  # failed fast on the first turn


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
