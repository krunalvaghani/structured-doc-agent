"""Tests for MCP tool content blocks."""

from extractor.tools.mcp_content import mcp_image_block, mcp_text_block


def test_mcp_image_block_uses_flat_mcp_format() -> None:
    block = mcp_image_block(b"\x89PNG\r\n", mime_type="image/png")
    assert block["type"] == "image"
    assert block["mimeType"] == "image/png"
    assert "data" in block
    assert "source" not in block
    assert block["data"]  # base64 non-empty


def test_mcp_text_block() -> None:
    assert mcp_text_block("hello") == {"type": "text", "text": "hello"}
