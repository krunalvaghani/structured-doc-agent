"""Integration tests — require OPENROUTER_API_KEY or ANTHROPIC_API_KEY."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from extractor.runner import parse_field_spec_json, run_extraction
from extractor.types import ExtractionOptions, ExtractionRequest

BOTTLES_PDF = Path(__file__).resolve().parents[1] / "storage" / "Bottles-CI-text.pdf"
INVOICE_PRESET = Path(__file__).resolve().parents[1] / "ui" / "presets" / "invoice.json"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_extract_bottles_ci_invoice() -> None:
    if not BOTTLES_PDF.is_file():
        pytest.skip("Bottles-CI-text.pdf not available")
    import os

    if not (
        os.environ.get("OPENROUTER_API_KEY")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        or os.environ.get("ANTHROPIC_API_KEY")
    ):
        pytest.skip("OPENROUTER_API_KEY or ANTHROPIC_API_KEY not set")

    spec = parse_field_spec_json(json.loads(INVOICE_PRESET.read_text()))
    request = ExtractionRequest(
        document_path=BOTTLES_PDF,
        field_spec=spec,
        options=ExtractionOptions(model="claude-haiku-4-5-20251001"),
    )
    result = await run_extraction(request)
    assert result.status in {"success", "needs_review"}
    if result.status == "success":
        assert result.data is not None
        assert "invoice_number" in result.data
        assert isinstance(result.data.get("line_items"), list)
        assert result.usage.cost_usd >= 0
