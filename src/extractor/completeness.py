"""Post-extraction completeness checks (empty arrays vs document content)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from extractor.parsing.pdf import extract_pdf_text
from extractor.parsing.registry import detect_kind

_MIN_TEXT_FOR_ARRAY_CHECK = 150


def _document_likely_has_repeating_entries(text: str, *, page_count: int = 1) -> bool:
    """Heuristic: document text likely contains multiple records for an array field.

    Records may appear as tables, blocks, sections, or scattered fields across pages —
    not only as formal tables.
    """
    if text.count("@") >= 2:
        return True
    if len(re.findall(r"\b\d{3}[\s./-]\d{3}[\s./-]\d", text)) >= 2:
        return True
    if len(re.findall(r"\+\d{2,}", text)) >= 2:
        return True
    substantive = [ln for ln in text.splitlines() if len(ln.strip()) >= 15]
    if len(substantive) >= 10:
        return True
    if page_count >= 2 and len(text.strip()) >= 250:
        return True
    return False


def check_list_completeness(
    data: dict[str, Any] | None,
    schema: dict[str, Any],
    document_path: Path,
    *,
    page_count: int = 1,
) -> list[str]:
    """Warn when array fields are empty but the document likely contains multiple records."""
    if not isinstance(data, dict):
        return []

    props = schema.get("properties") or {}
    array_fields = [
        name
        for name, prop in props.items()
        if isinstance(prop, dict) and prop.get("type") == "array"
    ]
    if not array_fields:
        return []

    empty_arrays = [name for name in array_fields if not data.get(name)]
    if not empty_arrays:
        return []

    kind = detect_kind(document_path)
    if kind == "pdf":
        text = extract_pdf_text(document_path)
        if not text or len(text.strip()) < _MIN_TEXT_FOR_ARRAY_CHECK:
            return []
        if not _document_likely_has_repeating_entries(text, page_count=page_count):
            return []
    elif kind == "image":
        return [
            f"'{name}': array is empty — verify the image was read and each record was extracted"
            for name in empty_arrays
        ]
    else:
        return []

    return [
        f"'{name}': returned no items but the document appears to contain multiple records — review"
        for name in empty_arrays
    ]
