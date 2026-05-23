# Extractor

Agentic PDF/image extraction using the Claude Agent SDK. Upload a document, define fields to extract, get validated JSON with live progress and cost tracking.

## Quick start

```bash
cd /home/krunal/python-workspace/voyfai/extractor
conda run -n voyfai uv pip install -e ".[dev]"

# Copy env template and set your OpenRouter key
cp .env.example .env
# Edit .env — set OPENROUTER_API_KEY (see .env.example)
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
conda run -n voyfai pytest -q -m integration
```

See [SPEC.md](SPEC.md) for full design.
