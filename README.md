# Structured Doc Agent

Agentic PDF/image extraction using the Claude Agent SDK and OpenRouter. Upload a document, define fields to extract, get validated JSON with live progress and cost tracking.

**Repo:** [github.com/krunalvaghani/structured-doc-agent](https://github.com/krunalvaghani/structured-doc-agent)

**Docs:** [ARCHITECTURE.md](ARCHITECTURE.md) (current design) · [SPEC.md](SPEC.md) (original spec)

## Quick start

```bash
git clone git@github.com:krunalvaghani/structured-doc-agent.git
cd structured-doc-agent
python -m venv .venv && source .venv/bin/activate   # or: conda activate voyfai
pip install -e ".[dev]"

# Copy env template and set your OpenRouter key
cp .env.example .env
# Edit .env — set OPENROUTER_API_KEY (see .env.example)
```

With the existing **conda** env `voyfai`:

```bash
conda run -n voyfai uv pip install -e ".[dev]"
```

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

### Run API + demo UI (recommended)

`conda run` hides uvicorn logs and can look "stuck" with no output. Use one of these instead:

**Option A — activate env first (best):**
```bash
conda activate voyfai
extractor serve --reload --port 8000
```

**Option B — conda run with visible output:**
```bash
conda run -n voyfai --no-capture-output extractor serve --reload --port 8000
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
conda activate voyfai
extractor run \
  --file storage/Bottles-CI-text.pdf \
  --field-spec ui/presets/invoice.json \
  --output result.json
```

### Tests

```bash
conda run -n voyfai pytest -q
conda run -n voyfai pytest -q -m integration   # live LLM; requires API key
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

Render auto-deploys on push to your default branch. GitHub Actions CI runs tests separately; no extra workflow is required for deploy.

See [ARCHITECTURE.md](ARCHITECTURE.md) for system design.
