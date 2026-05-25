"""JSON parsing helpers."""

from __future__ import annotations

import json

import pytest

from extractor.json_util import parse_assistant_json, parse_json_text


def test_parse_json_text_from_fence() -> None:
    assert parse_json_text('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_assistant_json_from_content() -> None:
    message = {"content": '{"invoice_number": "X"}'}
    assert parse_assistant_json(message) == {"invoice_number": "X"}


def test_parse_assistant_json_from_parsed_field() -> None:
    message = {"content": "", "parsed": {"invoice_number": "Y"}}
    assert parse_assistant_json(message) == {"invoice_number": "Y"}


def test_parse_assistant_json_from_reasoning_when_content_empty() -> None:
    message = {
        "content": "",
        "reasoning": 'Looking at the scan… final answer:\n{"carrier_company": "Acme"}',
    }
    assert parse_assistant_json(message) == {"carrier_company": "Acme"}


def test_parse_assistant_json_refusal() -> None:
    with pytest.raises(ValueError, match="refused"):
        parse_assistant_json({"content": "", "refusal": "Cannot process this document"})


def test_parse_assistant_json_empty_raises() -> None:
    with pytest.raises(ValueError, match="empty"):
        parse_assistant_json({"content": ""})
