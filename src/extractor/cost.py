"""Token usage aggregation and USD estimates."""

from __future__ import annotations

import json
import os
from typing import Any

from extractor.models import model_short_label, pricing_for_model
from extractor.types import StageUsage, UsageSummary

_DEFAULT_PRICING: dict[str, tuple[float, float]] = {}


def _pricing_table() -> dict[str, tuple[float, float]]:
    raw = os.environ.get("OPENROUTER_PRICING_JSON") or os.environ.get("ANTHROPIC_PRICING_JSON")
    if not raw:
        return dict(_DEFAULT_PRICING)
    try:
        data = json.loads(raw)
        out: dict[str, tuple[float, float]] = {}
        for key, val in data.items():
            if isinstance(val, dict):
                out[key] = (float(val.get("0", val.get("input", 0))), float(val.get("1", val.get("output", 0))))
            else:
                out[key] = (float(val[0]), float(val[1]))
        return out
    except (json.JSONDecodeError, TypeError, ValueError, IndexError):
        return dict(_DEFAULT_PRICING)


def rates_for_model(model_id: str) -> tuple[float, float]:
    table = _pricing_table()
    if model_id in table:
        return table[model_id]
    return pricing_for_model(model_id)


def estimate_cost_usd(model_id: str, input_tokens: int, output_tokens: int) -> float:
    in_rate, out_rate = rates_for_model(model_id)
    return (input_tokens / 1_000_000.0) * in_rate + (output_tokens / 1_000_000.0) * out_rate


def usage_from_result_message(
    message: Any,
    *,
    stage: str,
    model_id: str,
    latency_ms: float,
    trust_sdk_cost: bool = True,
) -> StageUsage:
    usage = getattr(message, "usage", None) or {}
    input_tokens = int(usage.get("input_tokens", 0) or 0)
    output_tokens = int(usage.get("output_tokens", 0) or 0)
    cache_read = int(usage.get("cache_read_input_tokens", 0) or 0)
    cache_create = int(usage.get("cache_creation_input_tokens", 0) or 0)
    cost = estimate_cost_usd(model_id, input_tokens, output_tokens)
    if trust_sdk_cost:
        sdk_cost = float(getattr(message, "total_cost_usd", 0) or 0)
        if sdk_cost > 0:
            cost = sdk_cost
    return StageUsage(
        stage=stage,
        model_id=model_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_create,
        cost_usd=cost,
        latency_ms=latency_ms,
    )


def usage_from_chat_completion(
    response: dict[str, Any],
    *,
    stage: str,
    model_id: str,
    latency_ms: float,
) -> StageUsage:
    usage = response.get("usage") or {}
    input_tokens = int(usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0) or 0)
    output_tokens = int(
        usage.get("completion_tokens", 0) or usage.get("output_tokens", 0) or 0
    )
    cost = estimate_cost_usd(model_id, input_tokens, output_tokens)
    return StageUsage(
        stage=stage,
        model_id=model_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
        latency_ms=latency_ms,
    )


def accumulate_stage_usage(summary: UsageSummary, stage_usage: StageUsage) -> None:
    summary.input_tokens += stage_usage.input_tokens
    summary.output_tokens += stage_usage.output_tokens
    summary.cache_read_input_tokens += stage_usage.cache_read_input_tokens
    summary.cache_creation_input_tokens += stage_usage.cache_creation_input_tokens
    summary.cost_usd = round(summary.cost_usd + stage_usage.cost_usd, 6)

    if stage_usage.stage in summary.by_stage:
        prev = summary.by_stage[stage_usage.stage]
        summary.by_stage[stage_usage.stage] = StageUsage(
            stage=stage_usage.stage,
            model_id=stage_usage.model_id,
            input_tokens=prev.input_tokens + stage_usage.input_tokens,
            output_tokens=prev.output_tokens + stage_usage.output_tokens,
            cache_read_input_tokens=prev.cache_read_input_tokens
            + stage_usage.cache_read_input_tokens,
            cache_creation_input_tokens=prev.cache_creation_input_tokens
            + stage_usage.cache_creation_input_tokens,
            cost_usd=round(prev.cost_usd + stage_usage.cost_usd, 6),
            latency_ms=prev.latency_ms + stage_usage.latency_ms,
        )
    else:
        summary.by_stage[stage_usage.stage] = stage_usage

    model_stats = summary.by_model.setdefault(
        stage_usage.model_id,
        {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
    )
    model_stats["input_tokens"] += stage_usage.input_tokens
    model_stats["output_tokens"] += stage_usage.output_tokens
    model_stats["cost_usd"] = round(model_stats["cost_usd"] + stage_usage.cost_usd, 6)


def merge_usage(summaries: list[UsageSummary]) -> UsageSummary:
    total = UsageSummary.empty()
    for summary in summaries:
        total.input_tokens += summary.input_tokens
        total.output_tokens += summary.output_tokens
        total.cache_read_input_tokens += summary.cache_read_input_tokens
        total.cache_creation_input_tokens += summary.cache_creation_input_tokens
        total.cost_usd += summary.cost_usd
        for stage, stage_usage in summary.by_stage.items():
            total.by_stage[stage] = stage_usage
        for model, model_usage in summary.by_model.items():
            if model not in total.by_model:
                total.by_model[model] = {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost_usd": 0.0,
                }
            total.by_model[model]["input_tokens"] += model_usage.get("input_tokens", 0)
            total.by_model[model]["output_tokens"] += model_usage.get("output_tokens", 0)
            total.by_model[model]["cost_usd"] = round(
                total.by_model[model]["cost_usd"] + model_usage.get("cost_usd", 0.0),
                6,
            )
    total.cost_usd = round(total.cost_usd, 6)
    return total


def stage_to_summary(stage_usage: StageUsage) -> UsageSummary:
    summary = UsageSummary.empty()
    summary.input_tokens = stage_usage.input_tokens
    summary.output_tokens = stage_usage.output_tokens
    summary.cache_read_input_tokens = stage_usage.cache_read_input_tokens
    summary.cache_creation_input_tokens = stage_usage.cache_creation_input_tokens
    summary.cost_usd = stage_usage.cost_usd
    summary.by_stage[stage_usage.stage] = stage_usage
    summary.by_model[stage_usage.model_id] = {
        "input_tokens": stage_usage.input_tokens,
        "output_tokens": stage_usage.output_tokens,
        "cost_usd": round(stage_usage.cost_usd, 6),
    }
    return summary


def format_cost_line(summary: UsageSummary, *, prefix: str = "") -> str:
    p = f"{prefix} " if prefix else ""
    parts = [
        f"{p}cost ${summary.cost_usd:.4f} "
        f"(tokens in={summary.input_tokens:,} out={summary.output_tokens:,})"
    ]
    for stage, stage_usage in summary.by_stage.items():
        short_model = model_short_label(stage_usage.model_id)
        parts.append(f"{stage}/{short_model} ${stage_usage.cost_usd:.4f}")
    return " | ".join(parts)
