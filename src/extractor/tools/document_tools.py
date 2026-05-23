"""MCP document tools with progress hooks."""

from __future__ import annotations

from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from extractor.tools.operations import (
    analyze_document as analyze_document_op,
    extract_pdf_text_tool as extract_pdf_text_op,
    get_document_metadata as get_document_metadata_op,
    render_pdf_pages_tool as render_pdf_pages_op,
)


@tool(
    "analyze_document",
    (
        "Analyze a document: page count, text density, file type, and recommended strategy. "
        "Always call this first before reading or extracting. "
        "Returns strategy=text_layer (has selectable text) or strategy=vision (scanned/image-only)."
    ),
    {"path": str},
)
async def analyze_document(args: dict[str, Any]) -> dict[str, Any]:
    return {"content": await analyze_document_op(args)}


@tool(
    "extract_pdf_text",
    "Extract selectable text from PDF pages",
    {"path": str, "page_numbers": list},
)
async def extract_pdf_text_tool(args: dict[str, Any]) -> dict[str, Any]:
    return {"content": await extract_pdf_text_op(args)}


@tool(
    "render_pdf_pages",
    (
        "Render PDF pages as PNG images for visual reading. "
        "Required for scanned/image-only PDFs (strategy=vision). "
        "Pass page_numbers=[1,2,...] to render specific pages; omit to render all pages. "
        "For multi-page documents, prefer batches of 1-3 pages at a time to stay within context limits."
    ),
    {"path": str, "page_numbers": list, "dpi": int},
)
async def render_pdf_pages_tool(args: dict[str, Any]) -> dict[str, Any]:
    return {"content": await render_pdf_pages_op(args)}


@tool(
    "get_document_metadata",
    "Get document metadata: MIME type, size, dimensions",
    {"path": str},
)
async def get_document_metadata(args: dict[str, Any]) -> dict[str, Any]:
    return {"content": await get_document_metadata_op(args)}


DOCUMENT_TOOLS = [
    analyze_document,
    extract_pdf_text_tool,
    render_pdf_pages_tool,
    get_document_metadata,
]

ALLOWED_TOOL_NAMES = [
    "mcp__extractor__analyze_document",
    "mcp__extractor__extract_pdf_text",
    "mcp__extractor__render_pdf_pages",
    "mcp__extractor__get_document_metadata",
]

document_mcp_server = create_sdk_mcp_server(
    name="extractor",
    version="1.0.0",
    tools=DOCUMENT_TOOLS,
)
