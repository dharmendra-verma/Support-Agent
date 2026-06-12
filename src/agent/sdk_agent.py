"""Production agentic harness built on the **Claude Agent SDK**.

This is the agent the product runs. The SDK *owns the agentic loop*
(model -> tool_use -> execute -> tool_result -> repeat -> end) — we do NOT
hand-write that loop here. Contrast ``src/agent/loop.py``, the direct
Messages-API reference implementation kept to demonstrate stop_reason control
flow (exam D1 TS 1.1).

Real symbols from ``claude_agent_sdk`` (see the SA-8 plan):
  query() / ClaudeSDKClient        -> drive the agent; iterate the message stream
  ClaudeAgentOptions               -> system_prompt, model, max_turns (the cap),
                                      mcp_servers, allowed_tools, permission_mode
  tool() / create_sdk_mcp_server   -> register in-process tools
  AssistantMessage / ResultMessage -> observe turns + usage/cost

SA-8 scaffold: structure/signatures are final; bodies land during the story.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable


@dataclass
class AgentResult:
    """What a completed agent run surfaces to callers (AC: usage tracking)."""

    text: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    num_turns: int = 0
    is_error: bool = False

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


# A runner maps (prompt, options) -> async stream of SDK messages. The real one
# is ``claude_agent_sdk.query``; tests inject a fake so the loop is exercised
# offline, without the SDK installed or any network.
Runner = Callable[..., AsyncIterator[Any]]


def build_options(
    *,
    system_prompt: str,
    model: str = "sonnet",
    max_turns: int = 25,
    mcp_servers: dict[str, Any] | None = None,
    allowed_tools: list[str] | None = None,
) -> Any:
    """Assemble ``ClaudeAgentOptions`` (imported lazily — keeps this module import-safe).

    ``max_turns`` is the SDK's iteration cap — the safety net, not a primary stop
    condition (the SDK terminates the loop itself when the model is done).
    """
    from claude_agent_sdk import ClaudeAgentOptions

    return ClaudeAgentOptions(
        system_prompt=system_prompt,
        model=model,
        max_turns=max_turns,
        mcp_servers=mcp_servers or {},
        allowed_tools=allowed_tools or [],
        permission_mode="default",
    )


def _name(message: Any) -> str:
    return type(message).__name__


def _consume(message: Any, result: AgentResult, text_parts: list[str]) -> None:
    """Fold one SDK message into ``result``. Duck-typed so test fakes work too.

    - Messages carrying ``content`` blocks (AssistantMessage/UserMessage) contribute
      their text — captured for visibility, never parsed to decide termination.
    - ResultMessage carries the authoritative cumulative ``usage``, ``num_turns``,
      cost, error flag, and the final ``result`` text. It is what ends the run.
    """
    content = getattr(message, "content", None)
    if content:
        for block in content:
            text = getattr(block, "text", None)
            if text:
                text_parts.append(text)

    if _name(message) == "ResultMessage" or hasattr(message, "total_cost_usd"):
        result.cost_usd = float(getattr(message, "total_cost_usd", 0.0) or 0.0)
        result.is_error = bool(getattr(message, "is_error", False))
        num_turns = getattr(message, "num_turns", None)
        if num_turns is not None:
            result.num_turns = int(num_turns)
        usage = getattr(message, "usage", None)
        if isinstance(usage, dict):
            result.input_tokens = int(usage.get("input_tokens", 0) or 0)
            result.output_tokens = int(usage.get("output_tokens", 0) or 0)
        final = getattr(message, "result", None)
        if final:
            result.text = final


async def run_support_agent(
    prompt: str,
    *,
    options: Any,
    runner: Runner | None = None,
) -> AgentResult:
    """Run one support request to completion via the Agent SDK.

    The SDK owns the agentic loop (tool_use -> tool_result -> repeat); we only
    consume the message stream it emits. Termination is observed via
    ``ResultMessage`` — the model's prose is never parsed to decide we're done.
    Tool outputs are visible to the model on the next turn automatically.
    """
    if runner is None:
        from claude_agent_sdk import query

        runner = query

    result = AgentResult()
    text_parts: list[str] = []
    async for message in runner(prompt=prompt, options=options):
        _consume(message, result, text_parts)

    # ResultMessage.result wins; otherwise stitch the streamed assistant text.
    if not result.text:
        result.text = "".join(text_parts)
    return result
