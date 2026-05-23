"""PDF parsing utilities."""

from __future__ import annotations

from pathlib import Path

import fitz
from pypdf import PdfReader

from extractor.logger import get_logger

log = get_logger(__name__)

MIN_PDF_TEXT_CHARS = 50
DEFAULT_PDF_RENDER_DPI = 200


def get_page_count(path: Path) -> int:
    reader = PdfReader(str(path))
    return len(reader.pages)


def extract_pdf_text(path: Path, *, page_numbers: list[int] | None = None) -> str:
    """Extract text from PDF text layer."""
    reader = PdfReader(str(path))
    indices = page_numbers or list(range(1, len(reader.pages) + 1))
    parts: list[str] = []
    for page_num in indices:
        if page_num < 1 or page_num > len(reader.pages):
            continue
        text = reader.pages[page_num - 1].extract_text() or ""
        if text.strip():
            parts.append(f"--- Page {page_num} ---\n{text}")
    return "\n\n".join(parts)


def text_density(path: Path) -> tuple[int, float]:
    """Return (page_count, avg_chars_per_page) from text layer."""
    reader = PdfReader(str(path))
    page_count = len(reader.pages)
    if page_count == 0:
        return 0, 0.0
    total = 0
    for page in reader.pages:
        total += len((page.extract_text() or "").strip())
    return page_count, total / page_count


def render_pdf_pages(
    path: Path,
    *,
    page_numbers: list[int] | None = None,
    dpi: int = DEFAULT_PDF_RENDER_DPI,
) -> list[tuple[int, bytes]]:
    """Render PDF pages to PNG bytes. Returns (page_number, png_bytes) pairs."""
    doc = fitz.open(str(path))
    try:
        if doc.page_count == 0:
            raise ValueError(f"PDF has no pages: {path}")
        indices = page_numbers or list(range(1, doc.page_count + 1))
        images: list[tuple[int, bytes]] = []
        for page_num in indices:
            if page_num < 1 or page_num > doc.page_count:
                continue
            page = doc[page_num - 1]
            pixmap = page.get_pixmap(dpi=dpi)
            images.append((page_num, pixmap.tobytes("png")))
        log.debug("rendered %d page(s) from %s", len(images), path.name)
        return images
    finally:
        doc.close()


def is_text_sparse(path: Path) -> bool:
    _, avg = text_density(path)
    return avg < MIN_PDF_TEXT_CHARS
