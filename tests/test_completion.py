"""OpenRouter API backend tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from extractor.completion.extraction import extract_with_completion
from extractor.config import Settings
from extractor.events import ProgressEmitter
from extractor.types import UsageSummary


def _settings(**overrides: object) -> Settings:
    from extractor.config import get_settings

    base = get_settings()
    defaults = dict(
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
        rate_limit_enabled=base.rate_limit_enabled,
        rate_limit_per_ip=base.rate_limit_per_ip,
        rate_limit_per_ip_window_seconds=base.rate_limit_per_ip_window_seconds,
        rate_limit_global_daily=base.rate_limit_global_daily,
    )
    defaults.update(overrides)
    return Settings(**defaults)


@pytest.fixture
def single_model_fallback_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests mock one chat sequence; avoid multi-model fallback chains."""

    def _chain(primary: str, **_: object) -> list[str]:
        return [primary]

    monkeypatch.setattr(
        "extractor.completion.extraction.completion_model_fallback_chain",
        _chain,
    )


@pytest.mark.asyncio
async def test_extract_with_completion_tool_loop_and_json(
    tmp_path: Path,
    single_model_fallback_chain: None,
) -> None:
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF")
    schema = {
        "type": "object",
        "properties": {"invoice_number": {"type": "string"}},
        "required": ["invoice_number"],
        "additionalProperties": False,
    }

    tool_turn = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "analyze_document",
                                "arguments": json.dumps({"path": str(pdf)}),
                            },
                        }
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }
    no_tools_turn = {
        "choices": [{"message": {"role": "assistant", "content": "Document read complete."}}],
        "usage": {"prompt_tokens": 50, "completion_tokens": 10},
    }
    final_turn = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": '{"invoice_number": "ABC-123"}',
                }
            }
        ],
        "usage": {"prompt_tokens": 200, "completion_tokens": 30},
    }

    mock_client = AsyncMock()
    mock_client.chat = AsyncMock(side_effect=[tool_turn, no_tools_turn, final_turn])

    with patch("extractor.completion.extraction.OpenRouterClient", return_value=mock_client):
        with patch(
            "extractor.completion.extraction.execute_tool",
            AsyncMock(return_value=[{"type": "text", "text": "PDF with 1 page(s)"}]),
        ):
            result, usage = await extract_with_completion(
                document_path=pdf,
                job_root=tmp_path,
                schema=schema,
                settings=_settings(),
                emitter=ProgressEmitter(),
            )

    assert result["status"] == "success"
    assert result["data"] == {"invoice_number": "ABC-123"}
    assert usage.input_tokens == 350
    assert usage.output_tokens == 60
    assert mock_client.chat.await_count == 3


@pytest.mark.asyncio
async def test_structured_extraction_retries_when_strict_schema_404(
    tmp_path: Path,
    single_model_fallback_chain: None,
) -> None:
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF")
    schema = {
        "type": "object",
        "properties": {"invoice_number": {"type": "string"}},
        "required": ["invoice_number"],
        "additionalProperties": False,
    }

    done_turn = {
        "choices": [{"message": {"role": "assistant", "content": "done"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    final_turn = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": '{"invoice_number": "ABC-123"}',
                }
            }
        ],
        "usage": {"prompt_tokens": 20, "completion_tokens": 8},
    }

    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    response = httpx.Response(404, request=request, text='{"error":{"message":"no endpoints"}}')
    http_404 = httpx.HTTPStatusError("404", request=request, response=response)

    mock_client = AsyncMock()
    mock_client.chat = AsyncMock(side_effect=[done_turn, http_404, final_turn])

    with patch("extractor.completion.extraction.OpenRouterClient", return_value=mock_client):
        result, _usage = await extract_with_completion(
            document_path=pdf,
            job_root=tmp_path,
            schema=schema,
            settings=_settings(),
            emitter=ProgressEmitter(),
        )

    assert result["status"] == "success"
    assert result["data"] == {"invoice_number": "ABC-123"}
    assert mock_client.chat.await_count == 3


@pytest.mark.asyncio
async def test_extract_falls_back_to_second_model_after_structured_404(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _two_model_chain(primary: str, **_: object) -> list[str]:
        return [primary, "google/gemini-2.5-flash"]

    monkeypatch.setattr(
        "extractor.completion.extraction.completion_model_fallback_chain",
        _two_model_chain,
    )
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF")
    schema = {
        "type": "object",
        "properties": {"invoice_number": {"type": "string"}},
        "required": ["invoice_number"],
        "additionalProperties": False,
    }

    done_turn = {
        "choices": [{"message": {"role": "assistant", "content": "done"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    success_turn = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": '{"invoice_number": "FALLBACK-1"}',
                }
            }
        ],
        "usage": {"prompt_tokens": 20, "completion_tokens": 8},
    }

    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    response = httpx.Response(404, request=request, text='{"error":{"message":"no endpoints"}}')
    http_404 = httpx.HTTPStatusError("404", request=request, response=response)

    mock_client = AsyncMock()

    async def chat_side_effect(*_args, **kwargs):
        model = kwargs.get("model", "")
        # Primary model: tool loop + three strict attempts all fail
        if model == "deepseek/deepseek-v3.2":
            if mock_client.chat.await_count < 1:
                return done_turn
            raise http_404
        # Fallback model succeeds on structured call
        return success_turn

    mock_client.chat = AsyncMock(side_effect=chat_side_effect)

    with patch("extractor.completion.extraction.OpenRouterClient", return_value=mock_client):
        result, _usage = await extract_with_completion(
            document_path=pdf,
            job_root=tmp_path,
            schema=schema,
            settings=_settings(extractor_model="deepseek-v3.2"),
            emitter=ProgressEmitter(),
            model="deepseek-v3.2",
        )

    assert result["status"] == "success"
    assert result["data"] == {"invoice_number": "FALLBACK-1"}
    assert result.get("model_fallback") is True


@pytest.mark.asyncio
async def test_extract_with_completion_requires_openrouter() -> None:
    result, usage = await extract_with_completion(
        document_path=Path("x.pdf"),
        job_root=Path("."),
        schema={"type": "object", "properties": {}},
        settings=_settings(openrouter_api_key=None),
        emitter=ProgressEmitter(),
    )
    assert result["status"] == "failed"
    assert "OPENROUTER" in (result.get("error") or "")
    assert usage == UsageSummary.empty()
