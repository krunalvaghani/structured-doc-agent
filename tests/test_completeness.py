"""Completeness check tests."""

from __future__ import annotations

from pathlib import Path

from extractor.completeness import (
    _document_likely_has_repeating_entries,
    check_list_completeness,
)


def test_empty_array_with_emails_flags_review(tmp_path: Path, monkeypatch) -> None:
    pdf = tmp_path / "list.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF")
    schema = {
        "type": "object",
        "properties": {
            "line_items": {
                "type": "array",
                "items": {"type": "object", "properties": {"email": {"type": "string"}}},
            }
        },
    }
    sample_text = (
        "Kinderhaus A\ninfo.a@example.com\n555-111-2222\n"
        "Kinderhaus B\ninfo.b@example.com\n555-333-4444\n" + "row data\n" * 12
    )
    monkeypatch.setattr("extractor.completeness.extract_pdf_text", lambda _path: sample_text)

    warnings = check_list_completeness({"line_items": []}, schema, pdf)

    assert warnings
    assert "line_items" in warnings[0]
    assert "records" in warnings[0]


def test_multipage_substantial_text_flags_empty_array(tmp_path: Path, monkeypatch) -> None:
    pdf = tmp_path / "multi.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF")
    schema = {
        "type": "object",
        "properties": {"line_items": {"type": "array", "items": {"type": "object"}}},
    }
    text = "Kinderhaus Nord\nSome address line\n" + ("detail line here\n" * 30)
    monkeypatch.setattr("extractor.completeness.extract_pdf_text", lambda _path: text)

    warnings = check_list_completeness({"line_items": []}, schema, pdf, page_count=3)

    assert warnings
    assert _document_likely_has_repeating_entries(text, page_count=3)


def test_empty_array_with_sparse_text_ok(tmp_path: Path, monkeypatch) -> None:
    pdf = tmp_path / "sparse.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF")
    schema = {
        "type": "object",
        "properties": {"line_items": {"type": "array", "items": {"type": "object"}}},
    }
    monkeypatch.setattr("extractor.completeness.extract_pdf_text", lambda _path: "Invoice header only")
    warnings = check_list_completeness({"line_items": []}, schema, pdf, page_count=1)
    assert warnings == []


def test_populated_array_no_warning(tmp_path: Path) -> None:
    pdf = tmp_path / "ok.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF")
    schema = {
        "type": "object",
        "properties": {"line_items": {"type": "array", "items": {"type": "object"}}},
    }
    data = {"line_items": [{"name": "A"}]}
    assert check_list_completeness(data, schema, pdf) == []
