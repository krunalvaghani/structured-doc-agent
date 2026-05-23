"""Tests for post-extraction verification."""

from __future__ import annotations

from pathlib import Path

from extractor.schema_builder import field_spec_to_json_schema
from extractor.types import FieldSpec
from extractor.verification import verify_extracted_data


def test_verify_flags_value_not_in_text(tmp_path: Path) -> None:
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 minimal")

    spec = FieldSpec.from_dict(
        {
            "fields": [
                {"name": "company_name", "label": "Company", "type": "string"},
            ]
        }
    )
    schema = field_spec_to_json_schema(spec)

    from extractor import verification as mod

    original_text = mod.extract_pdf_text
    original_sparse = mod.is_text_sparse
    mod.extract_pdf_text = lambda _path: "Acme Logistics GmbH"
    mod.is_text_sparse = lambda _path: False
    try:
        warnings, meta = verify_extracted_data(
            {"company_name": "Totally Fake Corp"},
            pdf_path,
            schema,
        )
    finally:
        mod.extract_pdf_text = original_text
        mod.is_text_sparse = original_sparse

    assert meta["verification"] == "text_layer"
    assert len(warnings) == 1
    assert "company_name" in warnings[0]


def test_verify_accepts_matching_value(tmp_path: Path) -> None:
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 minimal")
    spec = FieldSpec.from_dict(
        {"fields": [{"name": "ref", "label": "Ref", "type": "string"}]}
    )
    schema = field_spec_to_json_schema(spec)

    from extractor import verification as mod

    original_text = mod.extract_pdf_text
    original_sparse = mod.is_text_sparse
    mod.extract_pdf_text = lambda _path: "Reference IMH-43837"
    mod.is_text_sparse = lambda _path: False
    try:
        warnings, _meta = verify_extracted_data(
            {"ref": "IMH-43837"},
            pdf_path,
            schema,
        )
    finally:
        mod.extract_pdf_text = original_text
        mod.is_text_sparse = original_sparse

    assert warnings == []


def test_verify_skips_sparse_pdf(tmp_path: Path) -> None:
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 minimal")
    spec = FieldSpec.from_dict(
        {"fields": [{"name": "x", "label": "X", "type": "string"}]}
    )
    schema = field_spec_to_json_schema(spec)

    from extractor import verification as mod

    original_text = mod.extract_pdf_text
    original_sparse = mod.is_text_sparse
    mod.extract_pdf_text = lambda _path: "enough text here for verify"
    mod.is_text_sparse = lambda _path: True
    try:
        warnings, meta = verify_extracted_data({"x": "missing"}, pdf_path, schema)
    finally:
        mod.extract_pdf_text = original_text
        mod.is_text_sparse = original_sparse

    assert warnings == []
    assert meta["verification"] == "skipped_sparse_pdf"


def test_verify_accepts_eu_formatted_amounts(tmp_path: Path) -> None:
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 minimal")
    spec = FieldSpec.from_dict(
        {
            "fields": [
                {"name": "total", "label": "Total", "type": "float"},
                {"name": "line_items", "label": "Items", "type": "array", "item_fields": [
                    {"name": "line_total", "label": "Line Total", "type": "float"},
                ]},
            ]
        }
    )
    schema = field_spec_to_json_schema(spec)

    from extractor import verification as mod

    original_text = mod.extract_pdf_text
    original_sparse = mod.is_text_sparse
    eu_text = "Total 48.060,00 and line 1.755,94 and 6.187,10"
    mod.extract_pdf_text = lambda _path: eu_text
    mod.is_text_sparse = lambda _path: False
    try:
        warnings, _meta = verify_extracted_data(
            {
                "total": 48060.0,
                "line_items": [{"line_total": 1755.94}, {"line_total": 6187.1}],
            },
            pdf_path,
            schema,
        )
    finally:
        mod.extract_pdf_text = original_text
        mod.is_text_sparse = original_sparse

    assert warnings == []


def test_verify_skips_null_values(tmp_path: Path) -> None:
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 minimal")
    spec = FieldSpec.from_dict(
        {"fields": [{"name": "missing", "label": "Missing", "type": "string"}]}
    )
    schema = field_spec_to_json_schema(spec)

    from extractor import verification as mod

    original_text = mod.extract_pdf_text
    original_sparse = mod.is_text_sparse
    mod.extract_pdf_text = lambda _path: "Some text"
    mod.is_text_sparse = lambda _path: False
    try:
        warnings, _meta = verify_extracted_data({"missing": None}, pdf_path, schema)
    finally:
        mod.extract_pdf_text = original_text
        mod.is_text_sparse = original_sparse

    assert warnings == []
