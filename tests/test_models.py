"""Model registry tests."""

from __future__ import annotations

from extractor.models import (
    get_model,
    models_for_provider,
    pricing_for_model,
    resolve_model_id,
)


def test_openrouter_resolves_kimi_and_deepseek() -> None:
    assert resolve_model_id(
        "kimi-k2.6", use_openrouter=True, default="claude-haiku-4-5-20251001"
    ) == "moonshotai/kimi-k2.6"
    assert resolve_model_id(
        "deepseek-v4-pro", use_openrouter=True, default="claude-haiku-4-5-20251001"
    ) == "deepseek/deepseek-v4-pro"
    assert resolve_model_id(
        "deepseek-v3.2", use_openrouter=True, default="claude-haiku-4-5-20251001"
    ) == "deepseek/deepseek-v3.2"
    assert resolve_model_id(
        "gemini-2.5-flash", use_openrouter=True, default="claude-haiku-4-5-20251001"
    ) == "google/gemini-2.5-flash"


def test_anthropic_provider_excludes_openrouter_only_models() -> None:
    ids = {m.id for m in models_for_provider("anthropic")}
    assert "claude-haiku-4-5-20251001" in ids
    assert "kimi-k2.6" not in ids
    assert "deepseek-v4-pro" not in ids


def test_openrouter_provider_lists_all_models() -> None:
    ids = {m.id for m in models_for_provider("openrouter")}
    assert "kimi-k2.6" in ids
    assert "deepseek-v4-pro" in ids
    assert "deepseek-v3.2" in ids
    assert "gemini-2.5-flash" in ids


def test_pricing_for_new_models() -> None:
    assert pricing_for_model("moonshotai/kimi-k2.6") == (0.95, 4.0)
    assert pricing_for_model("google/gemini-2.5-flash") == (0.30, 2.50)
    assert pricing_for_model("deepseek/deepseek-v3.2") == (0.252, 0.378)
    assert pricing_for_model("deepseek/deepseek-v4-pro") == (0.435, 0.87)


def test_get_model_by_slug() -> None:
    assert get_model("anthropic/claude-haiku-4.5") is not None
    assert get_model("moonshotai/kimi-k2.6") is not None
