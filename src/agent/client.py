"""Thin wrapper over the Anthropic Messages API with cumulative usage accounting.

Kept separate from loop.py so the loop can be unit-tested against a fake client
(no network) — see tests/test_loop.py.

SA-8 scaffold: signatures are final; bodies are implemented during the story.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Usage:
    """Cumulative token usage across a conversation (AC: token tracking)."""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def add(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens


class MessagesClient(Protocol):
    """Minimal surface the loop needs — lets tests inject a fake."""

    def create(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        system: str | None = None,
    ) -> Any:  # returns an Anthropic Message
        ...


@dataclass
class AnthropicClient:
    """Real client backed by the ``anthropic`` SDK. Tracks cumulative usage."""

    model: str
    max_tokens: int = 4096
    usage: Usage = field(default_factory=Usage)
    _sdk: Any = None  # anthropic.Anthropic(), constructed lazily

    def create(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        system: str | None = None,
    ) -> Any:
        raise NotImplementedError("SA-8: call self._sdk.messages.create(...) and record usage")
