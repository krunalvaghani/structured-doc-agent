"""Mocked orchestrator tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from extractor.runner import run_extraction
from extractor.types import ExtractionOptions, ExtractionRequest, FieldDefinition, FieldSpec, UsageSummary


@pytest.mark.asyncio
async def test_run_extraction_field_spec_path() -> None:
    pdf = Path(__file__).resolve().parents[1] / "storage" / "Bottles-CI-text.pdf"
    if not pdf.is_file():
        pytest.skip("Bottles-CI-text.pdf not available")

    spec = FieldSpec(
        fields=[FieldDefinition(name="invoice_number", label="Invoice Number", type="string")]
    )
    request = ExtractionRequest(
        document_path=pdf,
        field_spec=spec,
        options=ExtractionOptions(backend="agent"),
    )

    mock_agent = AsyncMock(
        return_value=(
            {"status": "success", "data": {"invoice_number": "248053B-E"}},
            UsageSummary.empty(),
        )
    )

    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
        with patch("extractor.runner.extract_with_agent", mock_agent):
            result = await run_extraction(request)

    assert result.status == "success"
    assert result.data == {"invoice_number": "248053B-E"}
    mock_agent.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_extraction_skips_verification_when_disabled() -> None:
    pdf = Path(__file__).resolve().parents[1] / "storage" / "Bottles-CI-text.pdf"
    if not pdf.is_file():
        pytest.skip("Bottles-CI-text.pdf not available")

    from extractor.config import Settings, get_settings

    base = get_settings()
    settings = Settings(
        anthropic_api_key="test-key",
        openrouter_api_key=None,
        anthropic_base_url=None,
        extractor_model=base.extractor_model,
        schema_model=base.schema_model,
        max_pages=base.max_pages,
        max_file_mb=base.max_file_mb,
        request_timeout_s=base.request_timeout_s,
        verify_text_layer=False,
        max_output_tokens=base.max_output_tokens,
        uploads_root=base.uploads_root,
        extraction_backend="agent",
        vision_model="kimi-k2.6",
        rate_limit_enabled=base.rate_limit_enabled,
        rate_limit_per_ip=base.rate_limit_per_ip,
        rate_limit_per_ip_window_seconds=base.rate_limit_per_ip_window_seconds,
        rate_limit_global_daily=base.rate_limit_global_daily,
    )
    spec = FieldSpec(
        fields=[FieldDefinition(name="invoice_number", label="Invoice Number", type="string")]
    )
    request = ExtractionRequest(document_path=pdf, field_spec=spec, options=ExtractionOptions())
    mock_agent = AsyncMock(
        return_value=(
            {"status": "success", "data": {"invoice_number": "248053B-E"}},
            UsageSummary.empty(),
        )
    )

    with patch("extractor.runner.extract_with_agent", mock_agent):
        with patch("extractor.runner.verify_extracted_data") as mock_verify_fn:
            mock_verify_fn.return_value = ([], {"verification": "text_layer"})
            result = await run_extraction(request, settings=settings)

    mock_verify_fn.assert_not_called()
    assert result.metadata.get("verification") == "disabled"


@pytest.mark.asyncio
async def test_run_extraction_openrouter_api_key() -> None:
    pdf = Path(__file__).resolve().parents[1] / "storage" / "Bottles-CI-text.pdf"
    if not pdf.is_file():
        pytest.skip("Bottles-CI-text.pdf not available")

    spec = FieldSpec(fields=[FieldDefinition(name="x", label="X", type="string")])
    request = ExtractionRequest(document_path=pdf, field_spec=spec)

    from extractor.config import Settings, get_settings

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
        verify_text_layer=base.verify_text_layer,
        max_output_tokens=base.max_output_tokens,
        uploads_root=base.uploads_root,
        extraction_backend="agent",
        vision_model="kimi-k2.6",
        rate_limit_enabled=base.rate_limit_enabled,
        rate_limit_per_ip=base.rate_limit_per_ip,
        rate_limit_per_ip_window_seconds=base.rate_limit_per_ip_window_seconds,
        rate_limit_global_daily=base.rate_limit_global_daily,
    )
    mock_agent = AsyncMock(
        return_value=({"status": "success", "data": {"x": "1"}}, UsageSummary.empty())
    )

    with patch("extractor.runner.extract_with_agent", mock_agent):
        result = await run_extraction(request, settings=settings)

    assert result.status == "success"
    mock_agent.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_extraction_api_backend() -> None:
    pdf = Path(__file__).resolve().parents[1] / "storage" / "Bottles-CI-text.pdf"
    if not pdf.is_file():
        pytest.skip("Bottles-CI-text.pdf not available")

    spec = FieldSpec(fields=[FieldDefinition(name="x", label="X", type="string")])
    request = ExtractionRequest(
        document_path=pdf,
        field_spec=spec,
        options=ExtractionOptions(backend="api"),
    )

    from extractor.config import Settings, get_settings

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
        verify_text_layer=base.verify_text_layer,
        max_output_tokens=base.max_output_tokens,
        uploads_root=base.uploads_root,
        extraction_backend="agent",
        vision_model="kimi-k2.6",
        rate_limit_enabled=base.rate_limit_enabled,
        rate_limit_per_ip=base.rate_limit_per_ip,
        rate_limit_per_ip_window_seconds=base.rate_limit_per_ip_window_seconds,
        rate_limit_global_daily=base.rate_limit_global_daily,
    )
    mock_api = AsyncMock(
        return_value=({"status": "success", "data": {"x": "1"}}, UsageSummary.empty())
    )

    with patch("extractor.runner.extract_with_completion", mock_api):
        with patch("extractor.runner.extract_with_agent") as mock_agent:
            result = await run_extraction(request, settings=settings)

    assert result.status == "success"
    assert result.metadata.get("extraction_backend") == "api"
    mock_api.assert_awaited_once()
    mock_agent.assert_not_called()


@pytest.mark.asyncio
async def test_run_extraction_missing_api_key(tmp_path: Path) -> None:
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF")
    spec = FieldSpec(fields=[FieldDefinition(name="x", label="X", type="string")])
    request = ExtractionRequest(document_path=pdf, field_spec=spec)

    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False):
        from extractor.config import Settings

        settings = Settings.from_env()
        settings = Settings(
            anthropic_api_key=None,
            openrouter_api_key=None,
            anthropic_base_url=None,
            extractor_model=settings.extractor_model,
            schema_model=settings.schema_model,
            max_pages=settings.max_pages,
            max_file_mb=settings.max_file_mb,
            request_timeout_s=settings.request_timeout_s,
            verify_text_layer=settings.verify_text_layer,
            max_output_tokens=settings.max_output_tokens,
            uploads_root=settings.uploads_root,
            extraction_backend="agent",
            vision_model="kimi-k2.6",
            rate_limit_enabled=settings.rate_limit_enabled,
            rate_limit_per_ip=settings.rate_limit_per_ip,
            rate_limit_per_ip_window_seconds=settings.rate_limit_per_ip_window_seconds,
            rate_limit_global_daily=settings.rate_limit_global_daily,
        )
        result = await run_extraction(request, settings=settings)

    assert result.status == "failed"
    assert "LLM API key" in (result.error or "")
