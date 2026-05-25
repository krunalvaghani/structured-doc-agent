"""Golden fixture evaluation — no LLM required."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from golden_eval import assert_bottles_ci_extraction, load_bottles_ci_golden

BOTTLES_PDF = Path(__file__).resolve().parents[1] / "storage" / "Bottles-CI-text.pdf"


def test_bottles_ci_golden_fixture_structure() -> None:
    golden = load_bottles_ci_golden()
    assert golden["data"]["invoice_number"] == "248053B-E"
    assert golden["data"]["line_items_count"] == 14
    assert len(golden["data"]["line_items_sample"]) >= 1


def test_bottles_ci_golden_values_present_in_pdf_text() -> None:
    """Deterministic check: golden scalars appear in the PDF text layer."""
    if not BOTTLES_PDF.is_file():
        pytest.skip("Bottles-CI-text.pdf not available")

    from extractor.parsing.pdf import extract_pdf_text

    text = extract_pdf_text(BOTTLES_PDF)
    golden = load_bottles_ci_golden()["data"]

    assert golden["invoice_number"] in text
    assert "48.060,00" in text or "48060" in text.replace(".", "").replace(",", "")

    for code in golden["line_items_must_include_codes"]:
        assert code in text


def test_assert_bottles_ci_extraction_passes_on_golden_data() -> None:
    golden = load_bottles_ci_golden()["data"]
    data = {
        "invoice_number": golden["invoice_number"],
        "total_amount_usd": golden["total_amount_usd"],
        "line_items": _full_line_items_from_sample(),
    }
    failures = assert_bottles_ci_extraction(data)
    assert failures == []


def _full_line_items_from_sample() -> list[dict]:
    """Build 14-row fixture from golden sample + required codes."""
    golden = load_bottles_ci_golden()["data"]
    rows: list[dict] = []
    for sample in golden["line_items_sample"]:
        rows.append(
            {
                "item_code": sample["item_code"],
                "description": sample.get("description_contains", "item"),
                "quantity": sample["quantity"],
                "unit_price_usd": sample["unit_price_usd"],
                "total_amount_usd": sample["total_amount_usd"],
                "hs_code": sample["hs_code"],
            }
        )
    required = set(golden["line_items_must_include_codes"]) - {r["item_code"] for r in rows}
    for code in required:
        rows.append(
            {
                "item_code": code,
                "description": code,
                "quantity": 1,
                "unit_price_usd": 1.0,
                "total_amount_usd": 1.0,
                "hs_code": "39233010",
            }
        )
    while len(rows) < golden["line_items_count"]:
        rows.append(
            {
                "item_code": f"FILL{len(rows)}",
                "description": "filler",
                "quantity": 1,
                "unit_price_usd": 1.0,
                "total_amount_usd": 1.0,
                "hs_code": "39233010",
            }
        )
    return rows[: golden["line_items_count"]]


def test_assert_bottles_ci_extraction_detects_wrong_invoice() -> None:
    data = json.loads(json.dumps(_minimal_passing_data()))
    data["invoice_number"] = "WRONG"
    failures = assert_bottles_ci_extraction(data)
    assert any("invoice_number" in msg for msg in failures)


def _minimal_passing_data() -> dict:
    golden = load_bottles_ci_golden()["data"]
    return {
        "invoice_number": golden["invoice_number"],
        "total_amount_usd": golden["total_amount_usd"],
        "line_items": _full_line_items_from_sample(),
    }
