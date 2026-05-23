"""Document reading strategy (text layer vs vision)."""

from __future__ import annotations

from pathlib import Path

from extractor.parsing.pdf import text_density
from extractor.parsing.registry import detect_kind

# Matches analyze_document in tools/operations.py
VISION_TEXT_DENSITY_THRESHOLD = 50


def document_needs_vision(path: Path) -> bool:
    """True for images and PDFs with little or no selectable text (scanned)."""
    kind = detect_kind(path)
    if kind == "image":
        return True
    _, avg_chars = text_density(path)
    return avg_chars < VISION_TEXT_DENSITY_THRESHOLD
