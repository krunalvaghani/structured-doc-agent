"""Shared document tool implementations (MCP agent + OpenRouter API)."""

from __future__ import annotations

from typing import Any

from extractor.events import ProgressEvent
from extractor.parsing.image import guess_image_mime, is_image_path
from extractor.parsing.pdf import (
    extract_pdf_text,
    get_page_count,
    is_text_sparse,
    render_pdf_pages,
    text_density,
)
from extractor.parsing.registry import detect_kind
from extractor.tools.context import get_tool_context
from extractor.tools.mcp_content import mcp_image_block, mcp_text_block


async def _emit_tool(event_type: str, message: str, *, detail: dict[str, Any] | None = None) -> None:
    ctx = get_tool_context()
    await ctx.emitter.emit(
        ProgressEvent(
            type=event_type,
            source="tool",
            stage="extraction",
            message=message,
            detail=detail,
        )
    )


async def analyze_document(args: dict[str, Any]) -> list[dict[str, Any]]:
    ctx = get_tool_context()
    path = ctx.path_guard.resolve_allowed(args["path"])
    await _emit_tool("tool_started", f"Analyzing {path.name}…", detail={"tool": "analyze_document"})

    kind = detect_kind(path)
    if kind == "pdf":
        pages, avg_chars = text_density(path)
        strategy = "vision" if avg_chars < 50 else "text_layer"
        summary = (
            f"PDF with {pages} page(s), avg {avg_chars:.0f} chars/page, "
            f"strategy={strategy}"
        )
    else:
        pages = 1
        strategy = "vision"
        summary = f"Image file ({path.suffix}), strategy=vision"

    await _emit_tool(
        "tool_completed",
        summary,
        detail={"tool": "analyze_document", "page_count": pages, "strategy": strategy},
    )
    return [mcp_text_block(summary)]


async def extract_pdf_text_tool(args: dict[str, Any]) -> list[dict[str, Any]]:
    ctx = get_tool_context()
    path = ctx.path_guard.resolve_allowed(args["path"])
    page_numbers = args.get("page_numbers") or None
    await _emit_tool(
        "tool_started",
        "Extracting PDF text layer…",
        detail={"tool": "extract_pdf_text", "pages": page_numbers},
    )
    text = extract_pdf_text(path, page_numbers=page_numbers)
    char_count = len(text)
    await _emit_tool(
        "tool_completed",
        f"Extracted {char_count} characters",
        detail={"tool": "extract_pdf_text", "char_count": char_count},
    )
    if not text or char_count < 50:
        warning = (
            "(no selectable text found — this PDF is likely scanned or image-only. "
            "Use render_pdf_pages to read it visually.)"
        )
        return [mcp_text_block(warning)]
    return [mcp_text_block(text)]


async def render_pdf_pages_tool(args: dict[str, Any]) -> list[dict[str, Any]]:
    ctx = get_tool_context()
    path = ctx.path_guard.resolve_allowed(args["path"])
    page_numbers = args.get("page_numbers") or None
    dpi = int(args.get("dpi") or 150)
    pages_label = page_numbers or "all"
    await _emit_tool(
        "tool_started",
        f"Rendering pages {pages_label}…",
        detail={"tool": "render_pdf_pages", "pages": page_numbers, "dpi": dpi},
    )
    rendered = render_pdf_pages(path, page_numbers=page_numbers, dpi=dpi)
    content: list[dict[str, Any]] = [
        mcp_text_block(f"Rendered {len(rendered)} page image(s). Read each image visually.")
    ]
    for page_num, png_bytes in rendered:
        content.append(mcp_text_block(f"Page {page_num}:"))
        content.append(mcp_image_block(png_bytes, mime_type="image/png"))
    await _emit_tool(
        "tool_completed",
        f"Rendered {len(rendered)} page(s)",
        detail={"tool": "render_pdf_pages", "page_count": len(rendered)},
    )
    return content


async def get_document_metadata(args: dict[str, Any]) -> list[dict[str, Any]]:
    ctx = get_tool_context()
    path = ctx.path_guard.resolve_allowed(args["path"])
    await _emit_tool("tool_started", "Reading metadata…", detail={"tool": "get_document_metadata"})
    kind = detect_kind(path)
    size = path.stat().st_size
    meta: dict[str, Any] = {"kind": kind, "size_bytes": size, "filename": path.name}
    if kind == "pdf":
        meta["page_count"] = get_page_count(path)
        meta["text_sparse"] = is_text_sparse(path)
    elif is_image_path(path):
        meta["mime"] = guess_image_mime(path)
    text = ", ".join(f"{k}={v}" for k, v in meta.items())
    await _emit_tool("tool_completed", text, detail={"tool": "get_document_metadata", **meta})
    return [mcp_text_block(text)]


TOOL_OPERATIONS: dict[str, Any] = {
    "analyze_document": analyze_document,
    "extract_pdf_text": extract_pdf_text_tool,
    "render_pdf_pages": render_pdf_pages_tool,
    "get_document_metadata": get_document_metadata,
}
