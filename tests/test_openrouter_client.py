"""OpenRouter client URL and error formatting tests."""

from __future__ import annotations

import pytest

from extractor.completion.openrouter_client import (
    chat_completions_url,
    normalize_openrouter_base_url,
)


@pytest.mark.parametrize(
    ("base", "expected"),
    [
        ("https://openrouter.ai/api", "https://openrouter.ai/api/v1/chat/completions"),
        ("https://openrouter.ai/api/", "https://openrouter.ai/api/v1/chat/completions"),
        (
            "https://openrouter.ai/api/v1",
            "https://openrouter.ai/api/v1/chat/completions",
        ),
        (
            "https://openrouter.ai/api/v1/",
            "https://openrouter.ai/api/v1/chat/completions",
        ),
    ],
)
def test_chat_completions_url(base: str, expected: str) -> None:
    assert chat_completions_url(base) == expected


def test_normalize_openrouter_base_url_strips_trailing_v1() -> None:
    assert normalize_openrouter_base_url("https://openrouter.ai/api/v1") == (
        "https://openrouter.ai/api"
    )
