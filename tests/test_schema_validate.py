"""Schema validation tests."""

from __future__ import annotations

import json
from pathlib import Path

from extractor.schema_builder import field_spec_to_json_schema
from extractor.schema_validate import is_valid_extraction_data, validation_errors
from extractor.types import FieldSpec


def _invoice_schema() -> dict:
    preset = Path(__file__).resolve().parents[1] / "ui" / "presets" / "invoice.json"
    from extractor.runner import parse_field_spec_json

    return field_spec_to_json_schema(parse_field_spec_json(json.loads(preset.read_text())))


def test_valid_minimal_invoice_passes() -> None:
    schema = _invoice_schema()
    data = {
        "invoice_number": "248053B-E",
        "total_amount_usd": 1234.56,
        "line_items": [
            {
                "item_code": "SKU1",
                "description": "Widget",
                "quantity": 10,
                "unit_price_usd": 1.5,
                "total_amount_usd": 15.0,
                "hs_code": "39233010",
            }
        ],
    }
    assert is_valid_extraction_data(data, schema)
    assert validation_errors(data, schema) == []


def test_extra_fields_and_wrong_names_fail() -> None:
    schema = _invoice_schema()
    bad = {
        "invoice_number": "248053B-E",
        "invoice_date": "14.08.2024",
        "shipment_method": "BY SEA",
        "line_items": [
            {
                "item_code": "X",
                "description": None,
                "quantity": "1008",
                "unit_price": "1,742",
                "total_amount": "1.755,94",
                "hs_code": "39233010",
            }
        ],
    }
    errors = validation_errors(bad, schema)
    assert errors
    assert not is_valid_extraction_data(bad, schema)
    joined = "\n".join(errors)
    assert "additional properties" in joined.lower() or "shipment_method" in joined.lower()
    assert "total_amount_usd" in joined.lower() or "required" in joined.lower()
