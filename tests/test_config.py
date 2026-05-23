"""Config env parsing tests."""

from __future__ import annotations

import os
from unittest.mock import patch

from extractor.config import Settings, env_bool


def test_env_bool_truthy() -> None:
    for val in ("true", "True", "1", "yes", "on"):
        assert env_bool("X", default=False) is False  # not set
    with patch.dict(os.environ, {"X": "true"}):
        assert env_bool("X") is True
    with patch.dict(os.environ, {"X": "false"}):
        assert env_bool("X") is False


def test_openrouter_settings_from_env() -> None:
    with patch.dict(
        os.environ,
        {
            "OPENROUTER_API_KEY": "sk-or-test",
            "ANTHROPIC_API_KEY": "",
            "ANTHROPIC_BASE_URL": "",
        },
        clear=False,
    ):
        settings = Settings.from_env()
    assert settings.use_openrouter is True
    assert settings.llm_provider == "openrouter"
    assert settings.anthropic_base_url == "https://openrouter.ai/api"
    assert settings.extractor_model == "kimi-k2.6"


def test_openrouter_routes_non_anthropic_model_env() -> None:
    settings = Settings(
        anthropic_api_key=None,
        openrouter_api_key="sk-or-test",
        anthropic_base_url="https://openrouter.ai/api",
        extractor_model="deepseek-v4-pro",
        schema_model="deepseek-v4-pro",
        max_pages=50,
        max_file_mb=25,
        request_timeout_s=300,
        verify_text_layer=False,
        max_output_tokens=8000,
        uploads_root=Settings.from_env().uploads_root,
        extraction_backend="agent",
        vision_model="kimi-k2.6",
    )
    env = settings.agent_sdk_env(model_slug="deepseek/deepseek-v4-pro")
    assert env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "8000"
    assert env["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "deepseek/deepseek-v4-pro"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "sk-or-test"
    assert env["ANTHROPIC_API_KEY"] == ""


def test_resolve_model_for_openrouter() -> None:
    settings = Settings(
        anthropic_api_key=None,
        openrouter_api_key="sk-or-test",
        anthropic_base_url="https://openrouter.ai/api",
        extractor_model="anthropic/claude-haiku-4.5",
        schema_model="anthropic/claude-haiku-4.5",
        max_pages=50,
        max_file_mb=25,
        request_timeout_s=300,
        verify_text_layer=False,
        max_output_tokens=8000,
        uploads_root=Settings.from_env().uploads_root,
        extraction_backend="agent",
        vision_model="kimi-k2.6",
    )
    assert settings.resolve_model("claude-sonnet-4-6", default=settings.extractor_model) == (
        "anthropic/claude-sonnet-4.6"
    )
    assert settings.resolve_model("anthropic/claude-opus-4.6", default=settings.extractor_model) == (
        "anthropic/claude-opus-4.6"
    )


def test_parse_extraction_backend() -> None:
    from extractor.config import parse_extraction_backend

    assert parse_extraction_backend(None) == "agent"
    assert parse_extraction_backend("agent") == "agent"
    assert parse_extraction_backend("api") == "api"
    assert parse_extraction_backend("openrouter") == "api"


def test_extractor_backend_from_env() -> None:
    with patch.dict(os.environ, {"EXTRACTOR_BACKEND": "api"}, clear=False):
        settings = Settings.from_env()
    assert settings.extraction_backend == "api"


def test_default_backend_is_api_when_unset() -> None:
    env = {k: v for k, v in os.environ.items() if k != "EXTRACTOR_BACKEND"}
    with patch.dict(os.environ, env, clear=True):
        settings = Settings.from_env()
    assert settings.extraction_backend == "api"


def test_direct_anthropic_settings() -> None:
    with patch.dict(
        os.environ,
        {"ANTHROPIC_API_KEY": "sk-ant-test", "OPENROUTER_API_KEY": ""},
        clear=False,
    ):
        settings = Settings.from_env()
    assert settings.use_openrouter is False
    assert settings.llm_provider == "anthropic"
    assert settings.resolve_model("claude-sonnet-4-6", default=settings.extractor_model) == (
        "claude-sonnet-4-6"
    )
