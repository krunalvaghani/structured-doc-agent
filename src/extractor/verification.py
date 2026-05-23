"""Post-extraction checks against document text."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from extractor.parsing.pdf import extract_pdf_text, is_text_sparse
from extractor.parsing.registry import detect_kind

_MIN_VERIFY_LEN = 3


def _normalize(text: str) -> str:
    lowered = text.lower()
    lowered = re.sub(r"[^\w\s.,/-]", "", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _eu_number_variants(value: int | float) -> list[str]:
    """European formatting: 1.755,94 and 48.060,00 (dot thousands, comma decimal)."""
    variants: list[str] = []
    num = float(value)
    sign = "-" if num < 0 else ""
    num = abs(num)

    int_part = int(num)
    dec_part = num - int_part
    grouped_int = f"{int_part:,}".replace(",", ".")

    if dec_part < 1e-9:
        variants.append(f"{sign}{grouped_int}")
        variants.append(f"{sign}{grouped_int},00")
        variants.append(f"{sign}{grouped_int},0")
        return variants

    cents = int(round(dec_part * 100))
    variants.append(f"{sign}{grouped_int},{cents:02d}")
    if cents % 10 == 0:
        variants.append(f"{sign}{grouped_int},{cents // 10}")
    variants.append(f"{sign}{grouped_int},{cents}")
    return variants


def _number_variants(value: int | float) -> list[str]:
    variants = {str(value)}
    if isinstance(value, float) and value.is_integer():
        variants.add(str(int(value)))
    text = str(value)
    if "." in text:
        variants.add(text.rstrip("0").rstrip("."))
    try:
        variants.add(f"{float(value):,.2f}")
        variants.add(f"{float(value):,.0f}")
        variants.update(_eu_number_variants(value))
    except (TypeError, ValueError):
        pass
    return list(variants)


def _value_in_text(value: Any, text: str, *, norm_text: str) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return str(value).lower() in text.lower()
    if isinstance(value, (int, float)):
        return any(v in text for v in _number_variants(value))
    raw = str(value).strip()
    if len(raw) < _MIN_VERIFY_LEN:
        return True
    if raw in text:
        return True
    return _normalize(raw) in norm_text


def _walk_values(
    data: Any,
    schema: dict[str, Any],
    *,
    text: str,
    norm_text: str,
    path: str,
    warnings: list[str],
) -> None:
    props = schema.get("properties") or {}
    if not isinstance(data, dict):
        return

    for key, prop_schema in props.items():
        if key not in data:
            continue
        value = data[key]
        field_path = f"{path}.{key}" if path else key

        if prop_schema.get("type") == "array":
            items_schema = (prop_schema.get("items") or {}) if isinstance(prop_schema, dict) else {}
            if not isinstance(value, list):
                continue
            item_props = items_schema.get("properties") or {}
            for index, row in enumerate(value):
                if not isinstance(row, dict):
                    continue
                for col, col_schema in item_props.items():
                    if col not in row:
                        continue
                    col_val = row[col]
                    if not _value_in_text(col_val, text, norm_text=norm_text):
                        warnings.append(
                            f"{field_path}[{index}].{col}: value not found in document text — review"
                        )
            continue

        if not _value_in_text(value, text, norm_text=norm_text):
            warnings.append(f"{field_path}: value not found in document text — review")


def verify_extracted_data(
    data: dict[str, Any] | None,
    document_path: Path,
    schema: dict[str, Any],
) -> tuple[list[str], dict[str, Any]]:
    """Return warnings and metadata when values cannot be matched to document text."""
    meta: dict[str, Any] = {"verification": "skipped"}
    if not data:
        return [], meta

    kind = detect_kind(document_path)
    if kind != "pdf":
        meta["verification"] = "skipped_non_pdf"
        return [], meta

    text = extract_pdf_text(document_path)
    if not text or len(text.strip()) < _MIN_VERIFY_LEN:
        meta["verification"] = "skipped_no_text_layer"
        return [], meta

    if is_text_sparse(document_path):
        meta["verification"] = "skipped_sparse_pdf"
        meta["verification_note"] = (
            "PDF text layer is too sparse; values likely came from page images — skipped"
        )
        return [], meta

    norm_text = _normalize(text)
    warnings: list[str] = []
    _walk_values(data, schema, text=text, norm_text=norm_text, path="", warnings=warnings)
    meta["verification"] = "text_layer"
    meta["unverified_field_count"] = len(warnings)
    return warnings, meta
