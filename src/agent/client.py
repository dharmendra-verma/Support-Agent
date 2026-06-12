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
    """Real client backed by the ``anthropic`` SDK. Tracks cumulative usage.

    Used by the direct-API reference loop (``loop.py``). The SDK client is built
    lazily so importing this module never requires an API key.
    """

    model: str
    max_tokens: int = 4096
    usage: Usage = field(default_factory=Usage)
    _sdk: Any = None  # anthropic.Anthropic(), constructed lazily

    def _client(self) -> Any:
        if self._sdk is None:
            import anthropic  # lazy: no key needed just to import the module

            self._sdk = anthropic.Anthropic()
        return self._sdk

    def create(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        system: str | None = None,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": messages,
            "tools": tools,
        }
        if system is not None:
            kwargs["system"] = system
        resp = self._client().messages.create(**kwargs)
        # Record this turn's usage on the client's own running tally. The loop
        # keeps the authoritative per-conversation total (see loop.run_agent).
        self.usage.add(resp.usage.input_tokens, resp.usage.output_tokens)
        return resp
