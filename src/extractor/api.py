"""FastAPI application."""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from extractor.config import PACKAGE_ROOT, STORAGE_ROOT, get_settings, parse_extraction_backend
from extractor.events import ProgressEmitter
from extractor.logger import configure_logging, get_logger
from extractor.models import models_for_provider
from extractor.runner import new_job_id, parse_field_spec_json, run_extraction
from extractor.rate_limit import RateLimitExceeded, client_ip, get_rate_limiter
from extractor.types import ExtractionOptions, ExtractionRequest

log = get_logger(__name__)

UI_DIR = PACKAGE_ROOT / "ui"
_UI_MOUNTED = UI_DIR.is_dir()


def _should_log_request(path: str) -> bool:
    """Skip noisy health probes and static asset fetches at INFO."""
    if path == "/health":
        return False
    if path.startswith("/ui/") and path not in {"/ui", "/ui/"}:
        return False
    return True


@asynccontextmanager
async def _lifespan(app: FastAPI):
    configure_logging(force=True)
    settings = get_settings()
    log.info(
        "starting Structured Doc Agent app_root=%s ui_mounted=%s storage_root=%s",
        PACKAGE_ROOT,
        _UI_MOUNTED,
        STORAGE_ROOT,
    )
    log.info(
        "config backend=%s llm_configured=%s provider=%s rate_limit=%s",
        settings.extraction_backend,
        settings.llm_configured,
        settings.llm_provider,
        settings.rate_limit_enabled,
    )
    if not _UI_MOUNTED:
        log.warning("ui directory not found at %s — /ui will return 404", UI_DIR)
    if not (STORAGE_ROOT / "Bottles-CI-text.pdf").is_file():
        log.warning("demo PDFs missing under %s", STORAGE_ROOT)
    yield
    log.info("shutting down Structured Doc Agent")


app = FastAPI(title="Structured Doc Agent", version="0.1.0", lifespan=_lifespan)

if _UI_MOUNTED:
    app.mount("/ui", StaticFiles(directory=str(UI_DIR), html=True), name="ui")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    path = request.url.path
    if not _should_log_request(path):
        return await call_next(request)

    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    except Exception:
        log.exception("unhandled error %s %s", request.method, path)
        raise
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        log.info(
            "%s %s %s %.0fms",
            request.method,
            path,
            status_code,
            duration_ms,
        )

_DEMO_PDF_NAMES = frozenset(
    {
        "Bottles-CI-text.pdf",
        "Test-1-image.pdf",
    }
)


@app.get("/demo-files/{filename}")
async def demo_file(filename: str) -> FileResponse:
    """Serve whitelisted demo PDFs from storage for the UI."""
    if filename not in _DEMO_PDF_NAMES:
        raise HTTPException(status_code=404, detail="demo file not found")
    path = STORAGE_ROOT / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="demo file not found")
    return FileResponse(path, media_type="application/pdf", filename=filename)


@app.get("/health")
async def health() -> dict[str, Any]:
    settings = get_settings()
    return {
        "status": "ok",
        "llm_configured": settings.llm_configured,
        "llm_provider": settings.llm_provider,
        "anthropic_api_key_configured": bool(settings.anthropic_api_key),
        "default_extraction_backend": settings.extraction_backend,
        "api_backend_available": settings.api_backend_available,
        "rate_limit_enabled": settings.rate_limit_enabled,
    }


@app.get("/v1/models")
async def list_models() -> dict[str, Any]:
    settings = get_settings()
    provider = settings.llm_provider
    use_openrouter = settings.use_openrouter
    models = models_for_provider(provider)
    return {
        "provider": provider,
        "models": [m.to_dict(use_openrouter=use_openrouter) for m in models],
    }


@app.get("/v1/quota")
async def get_quota(request: Request) -> dict[str, Any]:
    settings = get_settings()
    limiter = get_rate_limiter(settings)
    return limiter.snapshot(client_ip(request))


def _enforce_rate_limit(request: Request) -> None:
    settings = get_settings()
    limiter = get_rate_limiter(settings)
    ip = client_ip(request)
    try:
        limiter.check_and_consume(ip)
    except RateLimitExceeded as exc:
        log.warning(
            "rate limit exceeded scope=%s ip=%s path=%s",
            exc.scope,
            ip,
            request.url.path,
        )
        raise HTTPException(status_code=429, detail=exc.to_dict()) from exc


@app.get("/v1/jobs/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
    from extractor.jobs import JOB_STORE

    record = JOB_STORE.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="job not found")
    return record.to_dict()


async def _save_upload(job_id: str, upload: UploadFile) -> Path:
    settings = get_settings()
    job_dir = settings.uploads_root / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    filename = upload.filename or "document"
    dest = job_dir / Path(filename).name
    with dest.open("wb") as out:
        shutil.copyfileobj(upload.file, out)
    return dest


def _parse_options(raw: str | None) -> ExtractionOptions:
    if not raw:
        return ExtractionOptions()
    data = json.loads(raw)
    return ExtractionOptions(
        model=data.get("model"),
        schema_model=data.get("schema_model"),
        max_budget_usd=data.get("max_budget_usd"),
        backend=parse_extraction_backend(data.get("backend")) if data.get("backend") else None,
    )


def _build_request(
    *,
    job_id: str,
    document_path: Path,
    field_spec: str | None,
    prompt: str | None,
    schema: str | None,
    options: ExtractionOptions,
) -> ExtractionRequest:
    req = ExtractionRequest(
        document_path=document_path,
        options=options,
        job_id=job_id,
    )
    if field_spec:
        req.field_spec = parse_field_spec_json(field_spec)
    elif prompt:
        req.prompt = prompt
    elif schema:
        req.schema = json.loads(schema)
    return req


@app.post("/v1/extract")
async def extract_sync(
    http_request: Request,
    file: UploadFile = File(...),
    field_spec: str | None = Form(None),
    prompt: str | None = Form(None),
    output_schema: str | None = Form(None, alias="schema"),
    options: str | None = Form(None),
) -> JSONResponse:
    _enforce_rate_limit(http_request)
    job_id = new_job_id()
    log.info(
        "extract sync job_id=%s file=%s client=%s",
        job_id,
        file.filename,
        client_ip(http_request),
    )
    path = await _save_upload(job_id, file)
    request = _build_request(
        job_id=job_id,
        document_path=path,
        field_spec=field_spec,
        prompt=prompt,
        schema=output_schema,
        options=_parse_options(options),
    )
    result = await run_extraction(request)
    log.info(
        "extract sync finished job_id=%s status=%s cost_usd=%.4f duration_ms=%s",
        job_id,
        result.status,
        result.usage.cost_usd,
        (result.metadata or {}).get("duration_ms"),
    )
    return JSONResponse(result.to_dict())


@app.post("/v1/extract/stream")
async def extract_stream(
    http_request: Request,
    file: UploadFile = File(...),
    field_spec: str | None = Form(None),
    prompt: str | None = Form(None),
    output_schema: str | None = Form(None, alias="schema"),
    options: str | None = Form(None),
) -> StreamingResponse:
    _enforce_rate_limit(http_request)
    job_id = new_job_id()
    log.info(
        "extract stream job_id=%s file=%s client=%s",
        job_id,
        file.filename,
        client_ip(http_request),
    )
    path = await _save_upload(job_id, file)
    request = _build_request(
        job_id=job_id,
        document_path=path,
        field_spec=field_spec,
        prompt=prompt,
        schema=output_schema,
        options=_parse_options(options),
    )
    emitter = ProgressEmitter()

    async def event_generator():
        run_task = asyncio.create_task(run_extraction(request, emitter=emitter))
        try:
            async for event in emitter.subscribe():
                yield event.to_sse()
        except asyncio.CancelledError:
            log.info("extract stream client disconnected job_id=%s", job_id)
            run_task.cancel()
            raise
        finally:
            if not run_task.done():
                run_task.cancel()
            try:
                result = await asyncio.shield(run_task)
            except asyncio.CancelledError:
                pass
            except Exception:
                log.exception("extract stream failed job_id=%s", job_id)
            else:
                log.info(
                    "extract stream finished job_id=%s status=%s cost_usd=%.4f",
                    job_id,
                    result.status,
                    result.usage.cost_usd,
                )

    # Cache-Control + X-Accel-Buffering prevent nginx/CDN proxies from buffering the stream.
    sse_headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=sse_headers,
    )


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Structured Doc Agent API", "ui": "/ui"}
