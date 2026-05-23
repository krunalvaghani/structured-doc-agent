"""OpenAI-format tool definitions for OpenRouter chat completions."""

from __future__ import annotations

from typing import Any

OPENROUTER_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "analyze_document",
            "description": (
                "Analyze a document: page count, text density, file type, and recommended strategy. "
                "Always call this first. Returns strategy=text_layer or strategy=vision."
            ),
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Document file path"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "extract_pdf_text",
            "description": "Extract selectable text from PDF pages",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "page_numbers": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "1-based page numbers; omit for all pages",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "render_pdf_pages",
            "description": (
                "Render PDF pages as PNG images for visual reading. "
                "Required for scanned/image-only PDFs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "page_numbers": {
                        "type": "array",
                        "items": {"type": "integer"},
                    },
                    "dpi": {"type": "integer", "description": "Render DPI, default 150"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_document_metadata",
            "description": "Get document metadata: MIME type, size, page count",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
]
