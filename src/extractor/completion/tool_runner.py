"""Execute document tools for the OpenRouter API backend."""

from __future__ import annotations

from typing import Any

from extractor.tools.operations import TOOL_OPERATIONS


async def execute_tool(name: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
    handler = TOOL_OPERATIONS.get(name)
    if handler is None:
        raise ValueError(f"unknown tool: {name}")
    return await handler(arguments)
