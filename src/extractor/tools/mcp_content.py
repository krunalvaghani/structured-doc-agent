"""MCP tool result content blocks (not Anthropic Messages API shape)."""

from __future__ import annotations

import base64
from typing import Any


def mcp_text_block(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def mcp_image_block(data: bytes, *, mime_type: str = "image/png") -> dict[str, Any]:
    """Image block for SDK MCP tool results — flat data + mimeType, no source wrapper."""
    return {
        "type": "image",
        "data": base64.b64encode(data).decode("ascii"),
        "mimeType": mime_type,
    }
