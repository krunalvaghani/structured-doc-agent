"""OpenRouter API backend tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

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
    )
    defaults.update(overrides)
    return Settings(**defaults)


@pytest.mark.asyncio
async def test_extract_with_completion_tool_loop_and_json(tmp_path: Path) -> None:
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
    mock_client.chat = AsyncMock(side_effect=[tool_turn, final_turn])

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
    assert usage.input_tokens == 300
    assert usage.output_tokens == 50
    assert mock_client.chat.await_count == 2


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
