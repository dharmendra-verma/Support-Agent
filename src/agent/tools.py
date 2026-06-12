"""Tool registry pattern.

A Tool bundles the JSON schema sent to the model with the Python handler that
executes it. The loop looks tools up by name when it sees a ``tool_use`` block.

SA-8 scaffold — handler bodies are filled in per story; the registry contract
below is what ``loop.py`` depends on.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], str]


class ToolRegistry:
    """Maps tool name -> Tool. Produces the ``tools=`` payload for the API."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def schemas(self) -> list[dict[str, Any]]:
        """The ``tools`` array passed to the Messages API."""
        return [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in self._tools.values()
        ]

    def dispatch(self, name: str, tool_input: dict[str, Any]) -> str:
        """Run the handler for ``name``. Raises KeyError on unknown tool."""
        return self._tools[name].handler(tool_input)
