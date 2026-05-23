"""Vision strategy and model selection tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from extractor.models import pick_extraction_model
from extractor.parsing.strategy import VISION_TEXT_DENSITY_THRESHOLD, document_needs_vision


def test_document_needs_vision_for_image(tmp_path: Path) -> None:
    img = tmp_path / "scan.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    assert document_needs_vision(img) is True


def test_pick_extraction_model_switches_text_only_for_scanned() -> None:
    choice = pick_extraction_model(
        needs_vision=True,
        model_option="deepseek-v3.2",
        use_openrouter=True,
        default_model="kimi-k2.6",
    )
    assert choice.vision_fallback is True
    assert choice.requested_id == "deepseek-v3.2"
    assert choice.effective_id == "kimi-k2.6"
    assert choice.needs_vision is True


def test_pick_extraction_model_keeps_vision_model() -> None:
    choice = pick_extraction_model(
        needs_vision=True,
        model_option="kimi-k2.6",
        use_openrouter=True,
        default_model="kimi-k2.6",
    )
    assert choice.vision_fallback is False
    assert choice.effective_id == "kimi-k2.6"


def test_pick_extraction_model_keeps_deepseek_for_text_pdf() -> None:
    choice = pick_extraction_model(
        needs_vision=False,
        model_option="deepseek-v3.2",
        use_openrouter=True,
        default_model="kimi-k2.6",
    )
    assert choice.vision_fallback is False
    assert choice.effective_id == "deepseek-v3.2"


def test_pick_extraction_model_anthropic_fallback_to_sonnet() -> None:
    choice = pick_extraction_model(
        needs_vision=True,
        model_option="claude-haiku-4-5-20251001",
        use_openrouter=False,
        default_model="claude-haiku-4-5-20251001",
    )
    assert choice.vision_fallback is True
    assert choice.effective_id == "claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_run_extraction_vision_fallback_for_scanned_pdf() -> None:
    pdf = Path(__file__).resolve().parents[1] / "storage" / "Test-1-image.pdf"
    if not pdf.is_file():
        pytest.skip("Test-1-image.pdf not available")
    if not document_needs_vision(pdf):
        pytest.skip("Test-1-image.pdf does not trigger vision strategy")

    from unittest.mock import AsyncMock, patch

    from extractor.config import Settings, get_settings
    from extractor.runner import run_extraction
    from extractor.types import ExtractionOptions, ExtractionRequest, FieldDefinition, FieldSpec, UsageSummary

    spec = FieldSpec(fields=[FieldDefinition(name="x", label="X", type="string")])
    request = ExtractionRequest(
        document_path=pdf,
        field_spec=spec,
        options=ExtractionOptions(model="deepseek-v3.2", backend="api"),
    )

    base = get_settings()
    settings = Settings(
        anthropic_api_key=None,
        openrouter_api_key="sk-or-test",
        anthropic_base_url="https://openrouter.ai/api",
        extractor_model=base.extractor_model,
        schema_model=base.schema_model,
        max_pages=base.max_pages,
        max_file_mb=base.max_file_mb,
        request_timeout_s=base.request_timeout_s,
        verify_text_layer=False,
        max_output_tokens=base.max_output_tokens,
        uploads_root=base.uploads_root,
        extraction_backend="api",
        vision_model="kimi-k2.6",
    )

    mock_api = AsyncMock(
        return_value=({"status": "success", "data": {"x": "1"}}, UsageSummary.empty())
    )

    with patch("extractor.runner.extract_with_completion", mock_api):
        result = await run_extraction(request, settings=settings)

    assert result.status == "success"
    assert result.metadata.get("vision_fallback") is True
    assert result.metadata["models_used"]["extraction_requested"] == "deepseek-v3.2"
    assert result.metadata["models_used"]["extraction"] == "kimi-k2.6"
    mock_api.assert_awaited_once()
    assert mock_api.await_args.kwargs["model"] == "kimi-k2.6"


def test_vision_threshold_matches_analyze_document() -> None:
    assert VISION_TEXT_DENSITY_THRESHOLD == 50
