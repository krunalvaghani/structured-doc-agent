"""Convert MCP tool blocks to OpenRouter / OpenAI message content."""

from __future__ import annotations

import json
from typing import Any


def mcp_blocks_to_tool_content(blocks: list[dict[str, Any]]) -> str | list[dict[str, Any]]:
    """Tool results for chat API — text-only or multimodal content array."""
    parts: list[dict[str, Any]] = []
    for block in blocks:
        kind = block.get("type")
        if kind == "text":
            parts.append({"type": "text", "text": block.get("text") or ""})
        elif kind == "image":
            mime = block.get("mimeType") or "image/png"
            data = block.get("data") or ""
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{data}"},
                }
            )
    if not parts:
        return ""
    if len(parts) == 1 and parts[0]["type"] == "text":
        return parts[0]["text"]
    return parts


def tool_result_message(tool_call_id: str, blocks: list[dict[str, Any]]) -> dict[str, Any]:
    content = mcp_blocks_to_tool_content(blocks)
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": content,
    }


def serialize_tool_arguments(raw: str | dict[str, Any] | None) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    return json.loads(raw)
