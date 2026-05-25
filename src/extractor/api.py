"""FastAPI application."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from extractor.config import PACKAGE_ROOT, STORAGE_ROOT, get_settings, parse_extraction_backend
from extractor.events import ProgressEmitter
from extractor.models import models_for_provider
from extractor.runner import new_job_id, parse_field_spec_json, run_extraction
from extractor.types import ExtractionOptions, ExtractionRequest

app = FastAPI(title="Structured Doc Agent", version="0.1.0")

UI_DIR = PACKAGE_ROOT / "ui"
if UI_DIR.is_dir():
    app.mount("/ui", StaticFiles(directory=str(UI_DIR), html=True), name="ui")

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
    file: UploadFile = File(...),
    field_spec: str | None = Form(None),
    prompt: str | None = Form(None),
    output_schema: str | None = Form(None, alias="schema"),
    options: str | None = Form(None),
) -> JSONResponse:
    job_id = new_job_id()
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
    return JSONResponse(result.to_dict())


@app.post("/v1/extract/stream")
async def extract_stream(
    file: UploadFile = File(...),
    field_spec: str | None = Form(None),
    prompt: str | None = Form(None),
    output_schema: str | None = Form(None, alias="schema"),
    options: str | None = Form(None),
) -> StreamingResponse:
    job_id = new_job_id()
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
            # Client disconnected — cancel the background extraction
            run_task.cancel()
            raise
        finally:
            if not run_task.done():
                run_task.cancel()
            try:
                await asyncio.shield(run_task)
            except (asyncio.CancelledError, Exception):
                pass

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
