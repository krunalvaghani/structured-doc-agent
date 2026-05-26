"""Document extraction via OpenRouter chat completions + tools.

Structured JSON uses a strict → relaxed → plain-chat retry ladder per model, then
``completion_model_fallback_chain()`` on retriable provider errors (404, 429, …).
See ARCHITECTURE.md §6 and ``models.COMPLETION_FALLBACK_MODEL_IDS``.
"""

from __future__ import annotations

import asyncio
import copy
import json
import time
from pathlib import Path
from typing import Any

import httpx

from extractor.agent.prompts import EXTRACTION_SYSTEM_PROMPT, build_extraction_user_prompt
from extractor.completion.content import serialize_tool_arguments, tool_result_message
from extractor.completion.openrouter_client import OpenRouterClient
from extractor.completion.tool_runner import execute_tool
from extractor.completion.tool_schemas import OPENROUTER_TOOL_DEFINITIONS
from extractor.config import Settings
from extractor.cost import accumulate_stage_usage, merge_usage, usage_from_chat_completion
from extractor.events import ProgressEmitter, ProgressEvent, pipeline_event
from extractor.json_util import parse_assistant_json
from extractor.logger import get_logger
from extractor.models import completion_model_fallback_chain, model_short_label
from extractor.security import PathGuard
from extractor.tools.context import ToolContext, clear_tool_context, set_tool_context
from extractor.schema_validate import validation_errors
from extractor.types import UsageSummary

log = get_logger(__name__)

MAX_TOOL_TURNS = 12
MAX_SCHEMA_RETRIES = 1

_RETRIABLE_HTTP_STATUS = frozenset({400, 404, 408, 429, 500, 502, 503, 504})
_RETRIABLE_MESSAGE_MARKERS = (
    "404",
    "no endpoints",
    "not available",
    "timeout",
    "timed out",
    "429",
    "rate limit",
)


def _schema_final_user_message(*, retry_errors: list[str] | None = None) -> str:
    parts = [
        "Return the extracted data as JSON that strictly matches the output schema.",
        "Use exact property names from the schema — do not rename fields or add extra keys.",
        "Use JSON numbers for numeric fields (not formatted strings like 1.755,94).",
        "For array fields: include one object per distinct record in the document (any layout); "
        "do not return [] if multiple records exist.",
        "Output JSON only — no markdown fences or commentary.",
    ]
    if retry_errors:
        parts.append("Previous response failed schema validation:")
        parts.extend(f"- {err}" for err in retry_errors[:15])
    return "\n".join(parts)


def _result_from_parsed(parsed: Any, schema: dict[str, Any]) -> dict[str, Any]:
    errors = validation_errors(parsed, schema)
    if errors:
        return {
            "status": "needs_review",
            "error": "schema_validation_failed",
            "data": parsed,
            "validation_errors": errors,
        }
    return {"status": "success", "data": parsed}


def _json_schema_response_format(schema: dict[str, Any], *, strict: bool) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "extraction_result",
            "strict": strict,
            "schema": schema,
        },
    }


def _is_retriable_openrouter_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRIABLE_HTTP_STATUS
    return _is_retriable_error_message(str(exc))


def _is_retriable_error_message(message: str) -> bool:
    lower = message.lower()
    return any(marker in lower for marker in _RETRIABLE_MESSAGE_MARKERS)


def _has_usable_result(result: dict[str, Any]) -> bool:
    status = result.get("status")
    if status == "success":
        return True
    if status == "needs_review" and result.get("data") is not None:
        return True
    return False


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


async def _request_structured_extraction(
    client: OpenRouterClient,
    *,
    messages: list[dict[str, Any]],
    model_id: str,
    schema: dict[str, Any],
    retry_errors: list[str] | None = None,
) -> dict[str, Any]:
    msgs = list(messages)
    if retry_errors:
        msgs.append(
            {
                "role": "user",
                "content": _schema_final_user_message(retry_errors=retry_errors),
            }
        )
    else:
        msgs.append(
            {
                "role": "user",
                "content": _schema_final_user_message(),
            }
        )

    attempts: list[dict[str, Any]] = [
        {
            "strict": True,
            "plugins": [{"id": "response-healing"}],
            "reasoning": {"effort": "none"},
        },
        {
            "strict": False,
            "plugins": [{"id": "response-healing"}],
            "reasoning": {"effort": "none"},
        },
        {"strict": False, "plugins": None, "reasoning": None},
    ]
    last_exc: Exception | None = None
    for index, attempt in enumerate(attempts):
        try:
            return await client.chat(
                msgs,
                model=model_id,
                response_format=_json_schema_response_format(schema, strict=attempt["strict"]),
                plugins=attempt["plugins"],
                reasoning=attempt["reasoning"],
            )
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            if exc.response.status_code not in (400, 404) or index == len(attempts) - 1:
                raise
            log.warning(
                "structured extraction fallback model=%s strict=%s plugins=%s status=%s",
                model_id,
                attempt["strict"],
                bool(attempt["plugins"]),
                exc.response.status_code,
            )
    if last_exc:
        raise last_exc
    raise RuntimeError("structured extraction failed without exception")


async def _request_plain_json_extraction(
    client: OpenRouterClient,
    *,
    messages: list[dict[str, Any]],
    model_id: str,
    retry_errors: list[str] | None = None,
) -> dict[str, Any]:
    msgs = list(messages)
    msgs.append(
        {
            "role": "user",
            "content": _schema_final_user_message(retry_errors=retry_errors),
        }
    )
    return await client.chat(msgs, model=model_id)


async def _run_tool_loop(
    client: OpenRouterClient,
    *,
    model_id: str,
    messages: list[dict[str, Any]],
    emitter: ProgressEmitter,
    deadline: float,
) -> tuple[str | None, UsageSummary, int]:
    usage = UsageSummary.empty()
    agent_event_count = 0

    for _ in range(MAX_TOOL_TURNS):
        if time.monotonic() > deadline:
            return "extraction timed out", usage, agent_event_count

        turn_start = time.monotonic()
        try:
            data = await client.chat(
                messages,
                model=model_id,
                tools=OPENROUTER_TOOL_DEFINITIONS,
                tool_choice="auto",
            )
        except Exception as exc:
            return str(exc) or type(exc).__name__, usage, agent_event_count

        accumulate_stage_usage(
            usage,
            usage_from_chat_completion(
                data,
                stage="extraction",
                model_id=model_id,
                latency_ms=(time.monotonic() - turn_start) * 1000,
            ),
        )

        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        tool_calls = message.get("tool_calls") or []

        if not tool_calls:
            if message.get("content"):
                messages.append(_assistant_message(message))
            return None, usage, agent_event_count

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

    return "tool loop exceeded max turns", usage, agent_event_count


async def _finalize_chat_response(
    *,
    final_data: dict[str, Any],
    model_id: str,
    schema: dict[str, Any],
    usage: UsageSummary,
    final_start: float,
    agent_event_count: int,
    emitter: ProgressEmitter,
    model_fallback: bool,
) -> tuple[dict[str, Any] | None, UsageSummary, str | None]:
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
        parsed = parse_assistant_json(final_message)
    except (ValueError, json.JSONDecodeError) as exc:
        return (
            {
                "status": "needs_review",
                "error": "could_not_parse_result_json",
                "raw_result": str(content or exc)[:500],
            },
            usage,
            None,
        )

    result_payload = _result_from_parsed(parsed, schema)
    if model_fallback and result_payload.get("status") in {"success", "needs_review"}:
        result_payload["model_fallback"] = True

    if _has_usable_result(result_payload):
        if result_payload["status"] == "success":
            await emitter.emit(
                pipeline_event(
                    "stage_completed",
                    "Extraction complete",
                    stage="extraction",
                    detail={
                        "agent_events": agent_event_count,
                        "backend": "api",
                        "model_id": model_id,
                        "model_fallback": model_fallback,
                    },
                )
            )
        return result_payload, usage, None

    schema_errors = result_payload.get("validation_errors") or []
    return result_payload, usage, None if schema_errors else "schema_validation_failed"


async def _run_structured_phase(
    client: OpenRouterClient,
    *,
    messages_base: list[dict[str, Any]],
    model_id: str,
    schema: dict[str, Any],
    emitter: ProgressEmitter,
    agent_event_count: int,
    model_fallback: bool,
) -> tuple[dict[str, Any] | None, UsageSummary, str | None]:
    usage = UsageSummary.empty()
    schema_errors: list[str] | None = None

    for attempt in range(MAX_SCHEMA_RETRIES + 1):
        final_start = time.monotonic()
        try:
            final_data = await _request_structured_extraction(
                client,
                messages=messages_base,
                model_id=model_id,
                schema=schema,
                retry_errors=schema_errors,
            )
        except Exception as exc:
            if _is_retriable_openrouter_error(exc):
                return None, usage, str(exc) or type(exc).__name__
            return (
                {"status": "failed", "error": str(exc) or type(exc).__name__},
                usage,
                None,
            )

        result_payload, usage, _ = await _finalize_chat_response(
            final_data=final_data,
            model_id=model_id,
            schema=schema,
            usage=usage,
            final_start=final_start,
            agent_event_count=agent_event_count,
            emitter=emitter,
            model_fallback=model_fallback,
        )
        if result_payload and _has_usable_result(result_payload):
            return result_payload, usage, None

        if result_payload and result_payload.get("status") == "needs_review":
            if attempt >= MAX_SCHEMA_RETRIES:
                await emitter.emit(
                    pipeline_event(
                        "agent_stream_warning",
                        "Schema validation failed after retries",
                        stage="extraction",
                        detail={"validation_errors": result_payload.get("validation_errors")},
                    )
                )
                return result_payload, usage, None

        schema_errors = (result_payload or {}).get("validation_errors") or []
        if attempt >= MAX_SCHEMA_RETRIES:
            break

        final_message = ((final_data.get("choices") or [{}])[0].get("message") or {})
        messages_base = list(messages_base)
        messages_base.append({"role": "assistant", "content": _message_content(final_message)})

    final_start = time.monotonic()
    try:
        final_data = await _request_plain_json_extraction(
            client,
            messages=messages_base,
            model_id=model_id,
            retry_errors=schema_errors,
        )
    except Exception as exc:
        if _is_retriable_openrouter_error(exc):
            return None, usage, str(exc) or type(exc).__name__
        return {"status": "failed", "error": str(exc) or type(exc).__name__}, usage, None

    result_payload, usage, _ = await _finalize_chat_response(
        final_data=final_data,
        model_id=model_id,
        schema=schema,
        usage=usage,
        final_start=final_start,
        agent_event_count=agent_event_count,
        emitter=emitter,
        model_fallback=model_fallback,
    )
    if result_payload and _has_usable_result(result_payload):
        return result_payload, usage, None
    if result_payload:
        return result_payload, usage, None
    return None, usage, "structured extraction produced no result"


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

    primary_slug = settings.resolve_model(model, default=settings.extractor_model)
    fallback_slugs = completion_model_fallback_chain(
        primary_slug,
        use_openrouter=settings.use_openrouter,
        default_model=settings.extractor_model,
        vision_model=settings.vision_model,
    )

    path_guard = PathGuard(job_root)
    ctx = ToolContext(
        job_root=job_root,
        document_path=document_path,
        emitter=emitter,
        path_guard=path_guard,
    )
    set_tool_context(ctx)

    client = OpenRouterClient(settings)
    total_usage = UsageSummary.empty()
    deadline = time.monotonic() + (timeout_s or settings.request_timeout_s)
    last_error: str | None = None

    try:
        for model_index, model_slug in enumerate(fallback_slugs):
            using_fallback = model_index > 0
            if using_fallback:
                label = model_short_label(model_slug)
                log.warning(
                    "completion model fallback attempt=%s model=%s",
                    model_index + 1,
                    model_slug,
                )
                await emitter.emit(
                    pipeline_event(
                        "stage_started",
                        f"Retrying extraction with fallback model: {label}",
                        stage="extraction",
                        detail={
                            "backend": "api",
                            "model_id": model_slug,
                            "model_fallback": True,
                            "fallback_attempt": model_index + 1,
                        },
                    )
                )

            messages: list[dict[str, Any]] = [
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": build_extraction_user_prompt(document_path, prompt, field_labels),
                },
            ]

            tool_error, tool_usage, agent_event_count = await _run_tool_loop(
                client,
                model_id=model_slug,
                messages=messages,
                emitter=emitter,
                deadline=deadline,
            )
            total_usage = merge_usage([total_usage, tool_usage])

            if tool_error:
                last_error = tool_error
                if _is_retriable_error_message(tool_error) and model_index < len(fallback_slugs) - 1:
                    continue
                return {"status": "failed", "error": tool_error}, total_usage

            messages_after_tools = copy.deepcopy(messages)
            structured_slugs = fallback_slugs[model_index:]

            for struct_index, struct_slug in enumerate(structured_slugs):
                struct_fallback = using_fallback or struct_index > 0
                if struct_index > 0:
                    label = model_short_label(struct_slug)
                    log.warning(
                        "structured output model fallback model=%s after tool loop",
                        struct_slug,
                    )
                    await emitter.emit(
                        pipeline_event(
                            "stage_started",
                            f"Retrying JSON extraction with {label}",
                            stage="extraction",
                            detail={
                                "backend": "api",
                                "model_id": struct_slug,
                                "model_fallback": True,
                            },
                        )
                    )

                result, struct_usage, struct_error = await _run_structured_phase(
                    client,
                    messages_base=messages_after_tools,
                    model_id=struct_slug,
                    schema=schema,
                    emitter=emitter,
                    agent_event_count=agent_event_count,
                    model_fallback=struct_fallback,
                )
                total_usage = merge_usage([total_usage, struct_usage])

                if result and _has_usable_result(result):
                    return result, total_usage
                if result and result.get("status") == "needs_review":
                    return result, total_usage
                if result and result.get("status") == "failed" and not struct_error:
                    return result, total_usage

                if struct_error:
                    last_error = struct_error
                    if (
                        _is_retriable_error_message(struct_error)
                        and struct_index < len(structured_slugs) - 1
                    ):
                        continue
                    if model_index < len(fallback_slugs) - 1 and _is_retriable_error_message(
                        struct_error
                    ):
                        break
                    return {"status": "failed", "error": struct_error}, total_usage

            if model_index < len(fallback_slugs) - 1:
                continue

    except asyncio.TimeoutError:
        last_error = f"extraction timed out after {timeout_s or settings.request_timeout_s}s"
    except Exception as exc:
        last_error = str(exc) or type(exc).__name__
    finally:
        clear_tool_context()

    if last_error:
        return {"status": "failed", "error": last_error}, total_usage
    return {"status": "failed", "error": "no_result"}, total_usage
