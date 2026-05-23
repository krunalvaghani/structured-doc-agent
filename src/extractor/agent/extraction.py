"""Extraction agent using Claude Agent SDK."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

from extractor.agent.prompts import EXTRACTION_SYSTEM_PROMPT, build_extraction_user_prompt
from extractor.agent.stream_adapter import AgentStreamAdapter
from extractor.config import Settings
from extractor.events import ProgressEmitter, pipeline_event
from extractor.json_util import parse_json_text
from extractor.security import PathGuard
from extractor.tools.context import ToolContext, clear_tool_context, set_tool_context
from extractor.tools.document_tools import ALLOWED_TOOL_NAMES, document_mcp_server
from extractor.types import UsageSummary


async def extract_with_agent(
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
    model_id = settings.resolve_model(model, default=settings.extractor_model)

    path_guard = PathGuard(job_root)
    ctx = ToolContext(
        job_root=job_root,
        document_path=document_path,
        emitter=emitter,
        path_guard=path_guard,
    )
    set_tool_context(ctx)

    options_kwargs: dict[str, Any] = {
        "model": model_id,
        "system_prompt": EXTRACTION_SYSTEM_PROMPT,
        "tools": [],
        "strict_mcp_config": True,
        "allowed_tools": ALLOWED_TOOL_NAMES,
        "mcp_servers": {"extractor": document_mcp_server},
        "permission_mode": "dontAsk",
        "include_partial_messages": True,
        "output_format": {"type": "json_schema", "schema": schema},
        "cwd": str(job_root),
    }
    if max_budget_usd is not None:
        options_kwargs["max_budget_usd"] = max_budget_usd
    if settings.llm_configured:
        options_kwargs["env"] = settings.agent_sdk_env(model_slug=model_id)

    options = ClaudeAgentOptions(**options_kwargs)
    adapter = AgentStreamAdapter(
        emitter,
        stage="extraction",
        model_id=model_id,
        trust_sdk_cost=not settings.use_openrouter,
    )
    usage = UsageSummary.empty()
    result_payload: dict[str, Any] | None = None
    stream_error: str | None = None

    try:
        async def _run() -> None:
            nonlocal usage, result_payload
            async for message in query(
                prompt=build_extraction_user_prompt(document_path, prompt, field_labels),
                options=options,
            ):
                stage_usage = await adapter.handle_message(message)
                if stage_usage is not None:
                    usage = stage_usage
                if isinstance(message, ResultMessage):
                    if message.is_error:
                        result_payload = {
                            "status": "failed",
                            "error": message.result or message.subtype or "agent_error",
                        }
                    elif message.subtype == "success" and message.structured_output:
                        result_payload = {
                            "status": "success",
                            "data": message.structured_output,
                        }
                    elif message.subtype == "success" and message.result:
                        try:
                            data = parse_json_text(message.result)
                            result_payload = {"status": "success", "data": data}
                        except (ValueError, json.JSONDecodeError):
                            result_payload = {
                                "status": "needs_review",
                                "error": "could_not_parse_result_json",
                                "raw_result": message.result[:500],
                            }
                    elif message.subtype == "error_max_structured_output_retries":
                        result_payload = {
                            "status": "needs_review",
                            "error": "schema_validation_exhausted",
                        }
                    elif message.subtype == "success":
                        result_payload = {
                            "status": "needs_review",
                            "error": "structured_output_missing",
                        }
                    else:
                        result_payload = {
                            "status": "failed",
                            "error": message.subtype or "agent_error",
                        }

        await asyncio.wait_for(_run(), timeout=timeout_s or settings.request_timeout_s)
    except TimeoutError:
        stream_error = f"extraction timed out after {timeout_s or settings.request_timeout_s}s"
    except Exception as exc:
        stream_error = str(exc) or type(exc).__name__
    finally:
        clear_tool_context()

    if result_payload and result_payload.get("status") == "success" and stream_error:
        await emitter.emit(
            pipeline_event(
                "agent_stream_warning",
                f"Agent returned data but stream ended with: {stream_error}",
                stage="extraction",
            )
        )
        return result_payload, usage

    if stream_error and result_payload is None:
        return {"status": "failed", "error": stream_error}, usage

    if adapter.agent_event_count == 0:
        await emitter.emit(
            pipeline_event(
                "heartbeat",
                "Agent stream partial — showing tool-level progress",
                stage="extraction",
            )
        )

    await emitter.emit(
        pipeline_event(
            "stage_completed",
            "Extraction complete",
            stage="extraction",
            detail={"agent_events": adapter.agent_event_count},
        )
    )

    if result_payload is None:
        return {"status": "failed", "error": "no_result"}, usage
    return result_payload, usage
