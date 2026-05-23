"""Cost estimation tests."""

from __future__ import annotations

from extractor.cost import estimate_cost_usd, usage_from_result_message


class _FakeResult:
    def __init__(self, *, total_cost_usd: float, usage: dict[str, int]) -> None:
        self.total_cost_usd = total_cost_usd
        self.usage = usage


def test_openrouter_uses_token_estimate_not_sdk_cost() -> None:
    msg = _FakeResult(
        total_cost_usd=0.1225,
        usage={"input_tokens": 7958, "output_tokens": 2021},
    )
    usage = usage_from_result_message(
        msg,
        stage="extraction",
        model_id="anthropic/claude-haiku-4.5",
        latency_ms=100.0,
        trust_sdk_cost=False,
    )
    expected = estimate_cost_usd("anthropic/claude-haiku-4.5", 7958, 2021)
    assert usage.cost_usd == expected
    assert usage.cost_usd < 0.03
    assert usage.cost_usd != 0.1225


def test_direct_anthropic_prefers_sdk_cost_when_available() -> None:
    msg = _FakeResult(
        total_cost_usd=0.0512,
        usage={"input_tokens": 7958, "output_tokens": 2021},
    )
    usage = usage_from_result_message(
        msg,
        stage="extraction",
        model_id="claude-sonnet-4-6",
        latency_ms=100.0,
        trust_sdk_cost=True,
    )
    assert usage.cost_usd == 0.0512


def test_falls_back_to_token_estimate_when_sdk_cost_missing() -> None:
    msg = _FakeResult(total_cost_usd=0.0, usage={"input_tokens": 1000, "output_tokens": 200})
    usage = usage_from_result_message(
        msg,
        stage="extraction",
        model_id="anthropic/claude-haiku-4.5",
        latency_ms=50.0,
        trust_sdk_cost=True,
    )
    assert usage.cost_usd == estimate_cost_usd("anthropic/claude-haiku-4.5", 1000, 200)
