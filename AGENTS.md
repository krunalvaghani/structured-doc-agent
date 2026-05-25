# Agent instructions — Structured Doc Agent

Guidance for AI coding agents working in this repository.

**Product:** Agentic PDF/image extraction → validated JSON. Users define fields (field spec, NL prompt, or JSON Schema); an LLM reads documents via tools and returns structured output with live progress and cost tracking.

**Docs:** [README.md](README.md) (setup) · [ARCHITECTURE.md](ARCHITECTURE.md) (system design) · [SPEC.md](SPEC.md) (historical product/API spec)

**Repo:** https://github.com/krunalvaghani/structured-doc-agent

---

## Architecture rules (read first)

1. **Single pipeline** — All entry points (UI, API, CLI) call `run_extraction()` in `src/extractor/runner.py`. Do not duplicate ingest → schema → extract → verify logic elsewhere.
2. **Two LLM backends, one orchestrator** — `EXTRACTOR_BACKEND=api` (OpenRouter chat + tool loop) or `agent` (Claude Agent SDK). Shared document tools; backend chosen in `runner.py`.
3. **Tool-first extraction** — The model must call document tools (`analyze_document`, `extract_pdf_text`, `render_pdf_pages`) before extracting. Prompts live in `src/extractor/agent/prompts.py`.
4. **Ground truth only** — Missing fields → `null` / `[]`; never invent values. Do not weaken this policy in prompts or post-processing.
5. **Progress is mandatory** — Pipeline and tool wrappers emit events via `ProgressEmitter` (`src/extractor/events.py`). Never gate basic stage visibility on the LLM stream.
6. **Default backend on PaaS** — Use `EXTRACTOR_BACKEND=api` for Render/Docker (see `render.yaml`).

---

## Repository layout

```
src/extractor/           # Python package (import name: extractor)
  runner.py              # Orchestrator — start here for pipeline changes
  api.py                 # FastAPI routes + SSE
  cli.py                 # extractor serve | extractor run
  config.py              # Settings from env
  models.py              # Model registry (IDs, slugs, pricing, vision fallback)
  types.py               # ExtractionRequest, ExtractionResult, FieldSpec, …
  events.py              # ProgressEmitter, SSE events
  jobs.py                # In-memory job store (poll fallback)
  schema_builder.py      # FieldSpec → JSON Schema (no LLM)
  schema_validate.py     # Post-extraction JSON Schema checks
  completeness.py        # Empty-array vs document heuristics
  verification.py        # Optional text-layer value checks
  cost.py                # Token/cost aggregation
  agent/                 # Claude Agent SDK path
    extraction.py
    schema_planner.py
    prompts.py
    stream_adapter.py
  completion/            # OpenRouter API path
    extraction.py
    openrouter_client.py
    tool_runner.py
    tool_schemas.py
  tools/                 # MCP / shared document tools
    document_tools.py
    operations.py
    context.py
  parsing/               # PDF text, render, images, strategy
tests/                   # pytest (pythonpath includes tests/ for golden_eval)
tests/golden_eval.py     # Golden fixture assertions (no LLM)
tests/fixtures/          # e.g. bottles_ci_expected.json
ui/                      # Static web UI (HTML/JS/CSS)
  app.js
  presets/               # invoice.json, demos.json, …
storage/                 # Demo PDFs (committed); uploads/ is gitignored
.github/workflows/ci.yml # pytest -m "not integration" on push
render.yaml              # Render Blueprint
Dockerfile
```

---

## Environment

Copy `.env.example` → `.env`. Never commit secrets.

| Variable | Purpose |
|----------|---------|
| `OPENROUTER_API_KEY` | Primary LLM auth (OpenRouter) |
| `ANTHROPIC_BASE_URL` | `https://openrouter.ai/api` when using OpenRouter |
| `ANTHROPIC_API_KEY` | Empty when using OpenRouter; set for direct Anthropic |
| `EXTRACTOR_BACKEND` | `api` (default) or `agent` |
| `EXTRACTOR_MODEL` | Extraction model (registry id or slug) |
| `EXTRACTOR_SCHEMA_MODEL` | Schema planner model (NL prompt mode) |
| `EXTRACTOR_VISION_MODEL` | Override vision fallback |
| `PORT` | Bind port for PaaS (read by `cli.py`; default 8000) |

Models and pricing: **`src/extractor/models.py`** only.

---

## Python environment

Requires **Python ≥ 3.11**. Use a virtual environment (recommended):

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

With **conda**, create or activate any env on Python 3.11+, then:

```bash
pip install -e ".[dev]"
# or: uv pip install -e ".[dev]"
```

Declare new dependencies in **`pyproject.toml`**, then reinstall editable.

---

## Commands

```bash
# API + web UI
extractor serve --reload --port 8000
# → http://127.0.0.1:8000/ui  ·  /health  ·  /v1/extract/stream

# CLI extraction
extractor run --file storage/Bottles-CI-text.pdf \
  --field-spec ui/presets/invoice.json --output result.json

# Tests (no API key)
pytest -q -m "not integration"

# Integration (live LLM; needs OPENROUTER_API_KEY or ANTHROPIC_API_KEY)
pytest -q -m integration

# Docker
docker build -t structured-doc-agent .
docker run --rm -p 8000:8000 --env-file .env structured-doc-agent
```

If `extractor serve` appears to hang with no logs, run uvicorn directly or ensure your process manager is not swallowing stdout.

---

## Coding conventions

- **Imports:** Absolute only — `from extractor.module import thing` (package name is `extractor`, not `structured-doc-agent`).
- **Logging:** `from extractor.logger import get_logger` → module-level `log = get_logger(__name__)`.
- **Types:** Type hints on public functions; prefer functions over classes unless stateful.
- **Scope:** Minimal diffs; match existing style; no drive-by refactors.
- **Tests:** pytest; mock LLM for unit tests; `@pytest.mark.integration` for live API calls.
- **Mermaid in docs:** Quote labels containing `/` — e.g. `A1["POST /v1/extract"]`, not `A1[/v1/extract]`.

---

## Where to change what

| Task | Location |
|------|----------|
| New API route | `src/extractor/api.py` → delegate to `runner.py` |
| Pipeline stage / validation | `src/extractor/runner.py` |
| New document tool | `src/extractor/tools/` + register in `document_tools.py`; mirror in `completion/tool_schemas.py` for API backend |
| Extraction prompts | `src/extractor/agent/prompts.py` |
| Agent SDK extraction | `src/extractor/agent/extraction.py` |
| OpenRouter tool loop | `src/extractor/completion/extraction.py` |
| Field spec → schema | `src/extractor/schema_builder.py` |
| Model list / pricing | `src/extractor/models.py` |
| SSE / progress events | `src/extractor/events.py` |
| Web UI | `ui/app.js`, `ui/index.html`, `ui/styles.css` |
| Golden expected values | `tests/fixtures/bottles_ci_expected.json`, `tests/golden_eval.py` |
| Deploy / PORT | `Dockerfile`, `render.yaml`, `cli.resolve_serve_bind()` |

---

## Testing expectations

- Run **`pytest -q -m "not integration"`** before finishing; CI runs the same on push.
- Add unit tests for new parsing, schema, validation, or cost logic.
- Use **`tests/test_golden_eval.py`** pattern for deterministic document assertions.
- Do not require API keys in default CI tests.

Demo fixtures: `storage/Bottles-CI-text.pdf`, `storage/Test-1-image.pdf`.

---

## Boundaries

**Do not:**

- Commit `.env`, API keys, or `storage/uploads/` contents
- Return unvalidated LLM output as `status: success`
- Add unrestricted SDK tools (`Bash`, `Read`, etc.) without explicit approval
- Duplicate pipeline logic in API, CLI, or UI
- Use relative imports inside `src/extractor/`

**Ask before:**

- Persisting extractions to a database
- New document formats (`.docx`, `.xlsx`, …)
- Changing default models or cost limits

---

## API surface (quick reference)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Liveness + LLM config status |
| GET | `/v1/models` | Model registry for UI |
| POST | `/v1/extract` | Sync extraction |
| POST | `/v1/extract/stream` | SSE progress + result |
| GET | `/v1/jobs/{job_id}` | Poll fallback |
| GET | `/ui` | Web UI (static) |

Request: multipart `file` + exactly one of `field_spec` | `prompt` | `schema`, optional `options` JSON.

---

## Git

- Default branch: **`main`**
- Only commit when the user asks
- Follow existing commit message style (concise, why-focused)
- Do not reference private or machine-specific environment names in docs or commit messages
