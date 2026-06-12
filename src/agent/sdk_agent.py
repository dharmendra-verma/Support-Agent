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

from dataclasses import dataclass, field
from typing import Any


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


def build_options(
    *,
    system_prompt: str,
    model: str = "sonnet",
    max_turns: int = 25,
    mcp_servers: dict[str, Any] | None = None,
    allowed_tools: list[str] | None = None,
) -> Any:
    """Assemble ``ClaudeAgentOptions``.

    ``max_turns`` is the SDK's iteration cap — the safety net, not a primary stop
    condition (the SDK terminates the loop itself when the model is done).
    """
    raise NotImplementedError(
        "SA-8: return ClaudeAgentOptions(system_prompt=..., model=..., max_turns=..., "
        "mcp_servers=..., allowed_tools=..., permission_mode='default')"
    )


async def run_support_agent(prompt: str, *, options: Any) -> AgentResult:
    """Run one support request to completion via the Agent SDK.

    Implementation outline (SA-8):
      result = AgentResult()
      async for message in query(prompt=prompt, options=options):
          if isinstance(message, AssistantMessage):
              # accumulate text blocks; fold message.usage into result tokens
          elif isinstance(message, ResultMessage):
              result.cost_usd = message.total_cost_usd
              result.is_error = message.is_error
              # ResultMessage.usage carries the authoritative cumulative totals
      return result

    Notes:
      - The SDK handles tool_use -> tool_result internally; tool outputs are
        visible to the model on the next turn automatically (the SA-8 context-
        accumulation AC is verified through an SDK run, not a hand-rolled loop).
      - Termination is observed via ResultMessage, never by parsing prose.
    """
    raise NotImplementedError("SA-8: drive query()/ClaudeSDKClient per the outline above")
