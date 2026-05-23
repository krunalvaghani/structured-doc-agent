"""Tests for field spec → JSON Schema conversion."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from extractor.schema_builder import field_spec_to_json_schema, validate_field_spec
from extractor.types import FieldSpec

INVOICE_PRESET = Path(__file__).resolve().parents[1] / "ui" / "presets" / "invoice.json"


def test_invoice_preset_to_schema() -> None:
    spec = FieldSpec.from_dict(json.loads(INVOICE_PRESET.read_text()))
    schema = field_spec_to_json_schema(spec)
    assert schema["type"] == "object"
    assert "invoice_number" in schema["properties"]
    assert schema["properties"]["line_items"]["type"] == "array"
    assert "description" in schema["properties"]["line_items"]["items"]["properties"]


def test_duplicate_field_names_rejected() -> None:
    spec = FieldSpec.from_dict(
        {
            "fields": [
                {"name": "a", "label": "A", "type": "string"},
                {"name": "a", "label": "B", "type": "string"},
            ]
        }
    )
    with pytest.raises(ValueError, match="duplicate"):
        validate_field_spec(spec)


def test_array_requires_item_fields() -> None:
    with pytest.raises(ValueError, match="item_fields"):
        FieldSpec.from_dict(
            {"fields": [{"name": "items", "label": "Items", "type": "array"}]}
        )


def test_invalid_field_name_rejected() -> None:
    spec = FieldSpec.from_dict(
        {"fields": [{"name": "Company Name", "label": "Company Name", "type": "string"}]}
    )
    with pytest.raises(ValueError, match="invalid"):
        validate_field_spec(spec)


def test_integer_and_float_schema_types() -> None:
    spec = FieldSpec.from_dict(
        {
            "fields": [
                {"name": "qty", "label": "Qty", "type": "integer"},
                {"name": "price", "label": "Price", "type": "float"},
            ]
        }
    )
    schema = field_spec_to_json_schema(spec)
    assert schema["properties"]["qty"]["type"] == ["integer", "null"]
    assert schema["properties"]["price"]["type"] == ["number", "null"]


def test_description_in_schema() -> None:
    spec = FieldSpec.from_dict(
        {
            "fields": [
                {
                    "name": "company_name",
                    "label": "Company Name",
                    "type": "string",
                    "description": "Legal name in the document header",
                }
            ]
        }
    )
    schema = field_spec_to_json_schema(spec)
    prop = schema["properties"]["company_name"]
    assert prop["description"].startswith("Company Name: Legal name in the document header")
    assert "null" in prop["description"].lower()
    assert prop["type"] == ["string", "null"]
    assert schema["required"] == ["company_name"]
