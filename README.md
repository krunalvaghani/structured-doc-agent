# Structured Doc Agent

Agentic PDF/image extraction using the Claude Agent SDK and OpenRouter. Upload a document, define fields to extract, get validated JSON with live progress and cost tracking.

**Repo:** [github.com/krunalvaghani/structured-doc-agent](https://github.com/krunalvaghani/structured-doc-agent)

**Docs:** [ARCHITECTURE.md](ARCHITECTURE.md) (current design) · [SPEC.md](SPEC.md) (original spec)

## What this project covers

End-to-end **document AI** sample: agentic extraction from PDFs/images to validated JSON, with a demo UI, API, and CLI.

### AI & LLM systems

| Area | What you get | Where |
|------|----------------|-------|
| **Agentic extraction** | Tool-first workflow (analyze → read text or render pages → structured JSON) | `runner.py`, `agent/`, `tools/` |
| **Structured output** | Field spec → JSON Schema; schema-constrained LLM responses; post-validation | `schema_builder.py`, `schema_validate.py` |
| **Trust & quality** | Anti-hallucination prompts; optional text-layer verification; golden fixture eval | `agent/prompts.py`, `verification.py`, `tests/golden_eval.py` |
| **Dual LLM backends** | Claude Agent SDK (MCP) **or** OpenRouter chat + tool loop — same pipeline | `agent/extraction.py`, `completion/extraction.py` |
| **Multimodal routing** | Text PDF vs scanned/image; automatic vision model fallback | `parsing/strategy.py`, `models.py` |
| **LLM observability** | Unified progress events (pipeline + agent + tools); SSE streaming | `events.py`, `api.py` |
| **Cost tracking** | Tokens and USD by stage/model; model registry with pricing | `cost.py`, `models.py` |
| **Provider flexibility** | OpenRouter or direct Anthropic; env-driven model selection | `config.py`, `models.py` |

### Product & engineering

| Area | What you get | Where |
|------|----------------|-------|
| **API surface** | Sync extract, SSE stream, job poll, models list, quota | `api.py` |
| **Web UI** | Upload, field builder, live activity feed, results, cost footer, quota UX | `ui/` |
| **CLI** | Scriptable extraction for automation | `cli.py` |
| **Document parsing** | PDF text layer, page rendering, image ingest (no LLM) | `parsing/` |
| **Public deploy** | Docker, Render blueprint, health checks, env-gated rate limits | `Dockerfile`, `render.yaml`, `rate_limit.py` |
| **Testing & CI** | Unit tests (mocked LLM), integration tests, GitHub Actions | `tests/`, `.github/workflows/ci.yml` |

### Typical use cases

| Use case | Supported |
|----------|-----------|
| Invoice / form field extraction | Yes |
| Scanned PDFs (vision) | Yes |
| Integrations via REST API | Yes |
| Live demo with cost visibility | Yes |
| RAG / embeddings / fine-tuning | Not in scope |
| Multi-user auth | Not in scope (v1) |

## Quick start

```bash
git clone git@github.com:krunalvaghani/structured-doc-agent.git
cd structured-doc-agent
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# Copy env template and set your OpenRouter key
cp .env.example .env
# Edit .env — set OPENROUTER_API_KEY (see .env.example)
```

Optional: use **conda** or **uv** on Python 3.11+ — `pip install -e ".[dev]"` (or `uv pip install -e ".[dev]"`) after activating your environment.

### LLM provider

The Agent SDK talks to **OpenRouter** by default. Set in `.env`:

```bash
OPENROUTER_API_KEY=sk-or-v1-...
ANTHROPIC_BASE_URL=https://openrouter.ai/api
ANTHROPIC_API_KEY=
```

`ANTHROPIC_API_KEY` must be empty when using OpenRouter (the SDK uses `ANTHROPIC_AUTH_TOKEN` instead). See [OpenRouter + Agent SDK](https://openrouter.ai/docs/guides/community/anthropic-agent-sdk).

For direct Anthropic instead, set `ANTHROPIC_API_KEY` and remove/unset the OpenRouter variables.

Models are defined in `src/extractor/models.py` (IDs, OpenRouter slugs, pricing). The UI loads the list from `GET /v1/models`. Override defaults with `EXTRACTOR_MODEL` / `EXTRACTOR_SCHEMA_MODEL` (registry id or full slug). Override pricing with `OPENROUTER_PRICING_JSON`.

### Run API + web UI (recommended)

With your virtual environment activated:

```bash
extractor serve --reload --port 8000
```

Or run uvicorn directly:

```bash
uvicorn extractor.api:app --reload --port 8000
```

Then open **http://127.0.0.1:8000/ui**

Verify the server is up:
```bash
curl http://127.0.0.1:8000/health
```

If port 8000 is already in use, pick another port:
```bash
extractor serve --reload --port 8001
```

### Docker

```bash
docker build -t structured-doc-agent .
docker run --rm -p 8000:8000 --env-file .env structured-doc-agent
```

Open **http://127.0.0.1:8000/ui**. LLM calls require `OPENROUTER_API_KEY` or `ANTHROPIC_API_KEY` in `.env`.

### CLI extraction

```bash
extractor run \
  --file storage/Bottles-CI-text.pdf \
  --field-spec ui/presets/invoice.json \
  --output result.json
```

### Tests

```bash
pytest -q
pytest -q -m integration   # live LLM; requires API key
```

Golden fixture eval (no LLM): `tests/test_golden_eval.py` checks expected invoice values against `tests/fixtures/bottles_ci_expected.json`.

CI runs unit tests on every push (see `.github/workflows/ci.yml`).

### Deploy on Render

The app reads **`PORT`** from the environment (Render injects this automatically). Use the **OpenRouter API** backend on PaaS (`EXTRACTOR_BACKEND=api`).

**Option A — Blueprint (fastest)**

1. Push this repo to GitHub.
2. In [Render](https://render.com): **New → Blueprint** → connect the repo.
3. Render reads `render.yaml` and creates the web service.
4. When prompted, set **`OPENROUTER_API_KEY`** (secret).
5. After deploy, open `https://<your-service>.onrender.com/ui`.

**Option B — Manual web service**

1. **New → Web Service** → connect repo.
2. **Runtime:** Docker (uses root `Dockerfile`).
3. **Health check path:** `/health`
4. **Plan:** Starter recommended (free tier sleeps when idle).
5. **Environment variables:**

   | Key | Value |
   |-----|--------|
   | `OPENROUTER_API_KEY` | your key (secret) |
   | `ANTHROPIC_BASE_URL` | `https://openrouter.ai/api` |
   | `ANTHROPIC_API_KEY` | *(empty)* |
   | `EXTRACTOR_BACKEND` | `api` |
   | `EXTRACTOR_HOST` | `0.0.0.0` |
   | `EXTRACTOR_RATE_LIMIT_ENABLED` | `true` (recommended on public deploy) |
   | `EXTRACTOR_RATE_LIMIT_PER_IP` | `5` (optional) |
   | `EXTRACTOR_RATE_LIMIT_GLOBAL_DAILY` | `20` (optional) |

Rate limits are **off by default** locally (`EXTRACTOR_RATE_LIMIT_ENABLED=false`). On a public deploy, enable them to cap OpenRouter spend: **5 extractions per IP per hour** and **20 globally per UTC day**. Check remaining quota with `GET /v1/quota`; extraction returns **429** with a JSON body when exhausted (no client IP is exposed). GitHub Actions CI runs tests separately; no extra workflow is required for deploy.

See [ARCHITECTURE.md](ARCHITECTURE.md) for system design.
