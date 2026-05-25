"""Orchestrate ingest, schema build, extraction, and progress."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any

from extractor.agent.extraction import extract_with_agent
from extractor.completion.extraction import extract_with_completion
from extractor.agent.schema_planner import plan_schema_from_prompt
from extractor.config import Settings, get_settings, resolve_extraction_backend
from extractor.cost import merge_usage
from extractor.events import ProgressEmitter, pipeline_event
from extractor.jobs import JOB_STORE
from extractor.parsing.pdf import get_page_count
from extractor.parsing.registry import detect_kind, validate_file_size
from extractor.models import pick_extraction_model
from extractor.parsing.strategy import document_needs_vision
from extractor.completeness import check_list_completeness
from extractor.schema_builder import describe_field_spec, field_spec_to_json_schema
from extractor.schema_validate import validation_errors
from extractor.logger import get_logger
from extractor.types import ExtractionRequest, ExtractionResult, FieldSpec, UsageSummary
from extractor.verification import verify_extracted_data

log = get_logger(__name__)


def new_job_id() -> str:
    return uuid.uuid4().hex


async def _heartbeat_loop(emitter: ProgressEmitter, stage: str, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=3.0)
        except TimeoutError:
            await emitter.emit(
                pipeline_event(
                    "heartbeat",
                    f"Still working… ({stage})",
                    stage=stage,
                )
            )


async def run_extraction(
    request: ExtractionRequest,
    *,
    settings: Settings | None = None,
    emitter: ProgressEmitter | None = None,
) -> ExtractionResult:
    settings = settings or get_settings()
    job_id = request.job_id or new_job_id()
    emitter = emitter or ProgressEmitter()
    JOB_STORE.create(job_id)

    start = time.monotonic()
    usages: list[UsageSummary] = []
    warnings: list[str] = []

    async def emit(event: Any) -> None:
        await emitter.emit(event)
        JOB_STORE.update_from_event(job_id, event)

    await emit(pipeline_event("run_started", "Starting extraction…"))

    if not settings.llm_configured:
        log.error("job_id=%s extraction aborted: LLM not configured", job_id)
        result = ExtractionResult(
            status="failed",
            error="LLM API key is not configured (set OPENROUTER_API_KEY or ANTHROPIC_API_KEY)",
            job_id=job_id,
        )
        await emit(
            pipeline_event(
                "run_failed",
                result.error or "failed",
                detail={"result": result.to_dict()},
            )
        )
        await emitter.close()
        return result

    try:
        request.validate_input_mode()
        path = request.document_path.resolve()
        await emit(
            pipeline_event(
                "file_received",
                f"Received {path.name} ({path.stat().st_size // 1024} KB)",
                stage="ingest",
            )
        )
        validate_file_size(path, max_mb=settings.max_file_mb)
        kind = detect_kind(path)
        page_count = get_page_count(path) if kind == "pdf" else 1
        if page_count > settings.max_pages:
            raise ValueError(f"document has {page_count} pages (max {settings.max_pages})")
        await emit(
            pipeline_event(
                "file_validated",
                f"Validated: {page_count} page(s), {kind.upper()}",
                stage="ingest",
            )
        )

        schema: dict[str, Any]
        field_labels: str | None = None

        if request.schema is not None:
            schema = request.schema
        elif request.field_spec is not None:
            await emit(
                pipeline_event("schema_build_started", "Building extraction schema…", stage="schema")
            )
            schema = field_spec_to_json_schema(request.field_spec)
            field_labels = describe_field_spec(request.field_spec)
            await emit(
                pipeline_event(
                    "schema_built",
                    f"Schema ready: {field_labels}",
                    stage="schema",
                )
            )
        else:
            schema, planner_usage = await plan_schema_from_prompt(
                request.prompt or "",
                settings=settings,
                emitter=emitter,
                model=request.options.schema_model,
            )
            usages.append(planner_usage)

        job_root = path.parent
        backend = resolve_extraction_backend(request.options.backend, settings)
        if backend == "api" and not settings.api_backend_available:
            raise ValueError(
                "API backend requires OPENROUTER_API_KEY (Agent SDK backend works with ANTHROPIC_API_KEY)"
            )

        needs_vision = document_needs_vision(path)
        model_choice = pick_extraction_model(
            needs_vision=needs_vision,
            model_option=request.options.model,
            use_openrouter=settings.use_openrouter,
            default_model=settings.extractor_model,
            vision_model=settings.vision_model,
        )
        log.info(
            "job_id=%s document=%s pages=%s backend=%s model=%s vision=%s fallback=%s",
            job_id,
            path.name,
            page_count,
            backend,
            model_choice.effective_id,
            needs_vision,
            model_choice.vision_fallback,
        )
        extraction_model_option = (
            model_choice.effective_id if model_choice.vision_fallback else request.options.model
        )

        backend_label = "OpenRouter API" if backend == "api" else "Agent SDK"
        if model_choice.vision_fallback:
            stage_message = (
                f"Model: {model_choice.label} · {backend_label} "
                f"(scanned document — switched from {model_choice.requested_label})"
            )
        else:
            stage_message = f"Model: {model_choice.label} · {backend_label}"

        await emit(
            pipeline_event(
                "stage_started",
                stage_message,
                stage="extraction",
                detail={
                    "backend": backend,
                    "model_id": model_choice.effective_id,
                    "model_slug": model_choice.resolved_slug,
                    "model_label": model_choice.label,
                    "model_requested": model_choice.requested_id,
                    "model_requested_label": model_choice.requested_label,
                    "vision_fallback": model_choice.vision_fallback,
                    "document_needs_vision": needs_vision,
                },
            )
        )

        stop_heartbeat = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            _heartbeat_loop(emitter, "extraction", stop_heartbeat)
        )
        extract_fn = extract_with_completion if backend == "api" else extract_with_agent
        try:
            agent_result, agent_usage = await extract_fn(
                document_path=path,
                job_root=job_root,
                schema=schema,
                settings=settings,
                emitter=emitter,
                model=extraction_model_option,
                prompt=request.prompt,
                field_labels=field_labels,
                max_budget_usd=request.options.max_budget_usd,
            )
        finally:
            stop_heartbeat.set()
            await heartbeat_task

        usages.append(agent_usage)
        total_usage = merge_usage(usages) if usages else UsageSummary.empty()
        duration_ms = (time.monotonic() - start) * 1000

        status = agent_result.get("status", "failed")
        data = agent_result.get("data")
        error = agent_result.get("error")
        verify_meta: dict[str, Any] = {}
        schema_validation_errors: list[str] = list(agent_result.get("validation_errors") or [])

        if status == "success" and data is not None and not schema_validation_errors:
            schema_validation_errors = validation_errors(data, schema)
            if schema_validation_errors:
                status = "needs_review"
                error = error or "schema_validation_failed"

        if schema_validation_errors:
            warnings.extend(f"Schema: {msg}" for msg in schema_validation_errors)
            verify_meta["validation_errors"] = schema_validation_errors

        completeness_warnings: list[str] = []
        if status in {"success", "needs_review"} and data is not None and isinstance(data, dict):
            completeness_warnings = check_list_completeness(
                data, schema, path, page_count=page_count
            )
            if completeness_warnings:
                warnings.extend(completeness_warnings)
                verify_meta["completeness_warnings"] = completeness_warnings
                if status == "success":
                    status = "needs_review"
                    error = error or "empty_list_extraction"

        if (
            settings.verify_text_layer
            and status == "success"
            and data
            and isinstance(data, dict)
        ):
            verify_warnings, verify_layer_meta = verify_extracted_data(data, path, schema)
            verify_meta.update(verify_layer_meta)
            if verify_warnings:
                warnings.extend(verify_warnings)
                await emit(
                    pipeline_event(
                        "verification_warnings",
                        f"Text check: {len(verify_warnings)} value(s) not in PDF text layer (may still be correct from vision)",
                        stage="verification",
                        detail={"warnings": verify_warnings},
                    )
                )
        elif not settings.verify_text_layer and not verify_meta:
            verify_meta = {"verification": "disabled"}

        result = ExtractionResult(
            status=status,  # type: ignore[arg-type]
            data=data,
            schema_used=schema,
            error=error,
            warnings=warnings,
            metadata={
                "page_count": page_count,
                "document_kind": kind,
                "duration_ms": round(duration_ms, 1),
                "extraction_backend": backend,
                "document_needs_vision": needs_vision,
                "vision_fallback": model_choice.vision_fallback,
                "models_used": {
                    "schema_planner": request.options.schema_model or settings.schema_model,
                    "extraction_requested": model_choice.requested_id,
                    "extraction": model_choice.effective_id,
                },
                **verify_meta,
            },
            usage=total_usage,
            job_id=job_id,
        )

        await emit(
            pipeline_event(
                "usage_ready",
                f"Total: ${total_usage.cost_usd:.4f} · {total_usage.input_tokens:,} in / {total_usage.output_tokens:,} out",
                detail={"usage": total_usage.to_dict()},
            )
        )
        finish_event = (
            "run_completed"
            if status in {"success", "needs_review"}
            else "run_failed"
        )
        finish_message = (
            "Extraction finished"
            if status in {"success", "needs_review"}
            else (error or "Extraction failed")
        )
        await emit(
            pipeline_event(
                finish_event,
                finish_message,
                detail={"result": result.to_dict()},
            )
        )
        JOB_STORE.complete(job_id, result.to_dict())
        await emitter.close()
        log.info(
            "job_id=%s finished status=%s cost_usd=%.4f duration_ms=%.0f warnings=%d",
            job_id,
            status,
            total_usage.cost_usd,
            duration_ms,
            len(warnings),
        )
        return result

    except Exception as exc:
        log.exception("job_id=%s extraction failed", job_id)
        total_usage = merge_usage(usages) if usages else UsageSummary.empty()
        result = ExtractionResult(
            status="failed",
            error=str(exc) or type(exc).__name__,
            usage=total_usage,
            job_id=job_id,
        )
        await emit(
            pipeline_event(
                "run_failed",
                str(exc) or type(exc).__name__,
                detail={"result": result.to_dict()},
            )
        )
        await emitter.close()
        return result


def parse_field_spec_json(raw: str | dict[str, Any]) -> FieldSpec:
    if isinstance(raw, str):
        data = json.loads(raw)
    else:
        data = raw
    return FieldSpec.from_dict(data)
