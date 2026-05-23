"""Document extraction via OpenRouter chat completions + tools."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from extractor.agent.prompts import EXTRACTION_SYSTEM_PROMPT, build_extraction_user_prompt
from extractor.completion.content import serialize_tool_arguments, tool_result_message
from extractor.completion.openrouter_client import OpenRouterClient
from extractor.completion.tool_runner import execute_tool
from extractor.completion.tool_schemas import OPENROUTER_TOOL_DEFINITIONS
from extractor.config import Settings
from extractor.cost import accumulate_stage_usage, usage_from_chat_completion
from extractor.events import ProgressEmitter, ProgressEvent, pipeline_event
from extractor.json_util import parse_json_text
from extractor.security import PathGuard
from extractor.tools.context import ToolContext, clear_tool_context, set_tool_context
from extractor.types import UsageSummary

MAX_TOOL_TURNS = 12


def _message_content(message: dict[str, Any]) -> str:
    content = message.get("content") or ""
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if part.get("type") == "text")
    return str(content)


def _assistant_message(message: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "role": "assistant",
        "content": message.get("content"),
    }
    if message.get("tool_calls"):
        out["tool_calls"] = message["tool_calls"]
    return out


async def extract_with_completion(
    *,
    document_path: Path,
    job_root: Path,
    schema: dict[str, Any],
    settings: Settings,
    emitter: ProgressEmitter,
    model: str | None = None,
    prompt: str | None = None,
    field_labels: str | None = None,
    timeout_s: int | None = None,
    max_budget_usd: float | None = None,
) -> tuple[dict[str, Any], UsageSummary]:
    del max_budget_usd  # budget cap is Agent SDK only for now

    if not settings.openrouter_api_key:
        return (
            {
                "status": "failed",
                "error": "API backend requires OPENROUTER_API_KEY",
            },
            UsageSummary.empty(),
        )

    model_id = settings.resolve_model(model, default=settings.extractor_model)

    path_guard = PathGuard(job_root)
    ctx = ToolContext(
        job_root=job_root,
        document_path=document_path,
        emitter=emitter,
        path_guard=path_guard,
    )
    set_tool_context(ctx)

    client = OpenRouterClient(settings)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": build_extraction_user_prompt(document_path, prompt, field_labels),
        },
    ]
    usage = UsageSummary.empty()
    agent_event_count = 0
    stream_error: str | None = None
    last_assistant_content: str | None = None
    deadline = time.monotonic() + (timeout_s or settings.request_timeout_s)

    try:
        for _ in range(MAX_TOOL_TURNS):
            if time.monotonic() > deadline:
                stream_error = f"extraction timed out after {timeout_s or settings.request_timeout_s}s"
                break

            turn_start = time.monotonic()
            try:
                data = await client.chat(
                    messages,
                    model=model_id,
                    tools=OPENROUTER_TOOL_DEFINITIONS,
                    tool_choice="auto",
                )
            except Exception as exc:
                stream_error = str(exc) or type(exc).__name__
                break

            latency_ms = (time.monotonic() - turn_start) * 1000
            accumulate_stage_usage(
                usage,
                usage_from_chat_completion(
                    data,
                    stage="extraction",
                    model_id=model_id,
                    latency_ms=latency_ms,
                ),
            )

            choice = (data.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            tool_calls = message.get("tool_calls") or []

            if not tool_calls:
                if message.get("content"):
                    messages.append(_assistant_message(message))
                    last_assistant_content = _message_content(message)
                break

            messages.append(_assistant_message(message))
            for tool_call in tool_calls:
                fn = tool_call.get("function") or {}
                tool_name = fn.get("name") or "unknown"
                raw_args = fn.get("arguments")
                try:
                    args = serialize_tool_arguments(raw_args)
                except json.JSONDecodeError:
                    args = {}

                agent_event_count += 1
                await emitter.emit(
                    ProgressEvent(
                        type="agent_tool_called",
                        source="agent",
                        stage="extraction",
                        message=f"Model calling {tool_name}",
                        detail={"tool": tool_name, "input": args, "backend": "api"},
                    )
                )

                try:
                    blocks = await execute_tool(tool_name, args)
                except Exception as exc:
                    blocks = [{"type": "text", "text": f"Tool error: {exc}"}]

                await emitter.emit(
                    ProgressEvent(
                        type="agent_tool_result",
                        source="agent",
                        stage="extraction",
                        message=f"{tool_name} completed",
                        detail={"tool": tool_name, "backend": "api"},
                    )
                )
                messages.append(
                    tool_result_message(tool_call.get("id") or tool_name, blocks)
                )

        if stream_error is None:
            if last_assistant_content:
                try:
                    parsed = parse_json_text(last_assistant_content)
                    await emitter.emit(
                        pipeline_event(
                            "stage_completed",
                            "Extraction complete",
                            stage="extraction",
                            detail={"agent_events": agent_event_count, "backend": "api"},
                        )
                    )
                    return {"status": "success", "data": parsed}, usage
                except (ValueError, json.JSONDecodeError):
                    pass

            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Return the extracted data as JSON matching the schema. "
                        "Output JSON only — no markdown fences or commentary."
                    ),
                }
            )
            final_start = time.monotonic()
            try:
                final_data = await client.chat(
                    messages,
                    model=model_id,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": "extraction_result",
                            "strict": True,
                            "schema": schema,
                        },
                    },
                )
            except Exception as exc:
                stream_error = str(exc) or type(exc).__name__
                final_data = None

            if final_data is not None:
                accumulate_stage_usage(
                    usage,
                    usage_from_chat_completion(
                        final_data,
                        stage="extraction",
                        model_id=model_id,
                        latency_ms=(time.monotonic() - final_start) * 1000,
                    ),
                )

                final_message = ((final_data.get("choices") or [{}])[0].get("message") or {})
                content = _message_content(final_message)

                try:
                    parsed = parse_json_text(content)
                    await emitter.emit(
                        pipeline_event(
                            "stage_completed",
                            "Extraction complete",
                            stage="extraction",
                            detail={"agent_events": agent_event_count, "backend": "api"},
                        )
                    )
                    return {"status": "success", "data": parsed}, usage
                except (ValueError, json.JSONDecodeError):
                    return {
                        "status": "needs_review",
                        "error": "could_not_parse_result_json",
                        "raw_result": str(content)[:500],
                    }, usage

    except asyncio.TimeoutError:
        stream_error = f"extraction timed out after {timeout_s or settings.request_timeout_s}s"
    except Exception as exc:
        stream_error = str(exc) or type(exc).__name__
    finally:
        clear_tool_context()

    if stream_error:
        return {"status": "failed", "error": stream_error}, usage
    return {"status": "failed", "error": "no_result"}, usage
