FROM python:3.11-slim

WORKDIR /app

# PyMuPDF wheels are available; keep image minimal.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY ui ./ui
COPY storage/Bottles-CI-text.pdf storage/Test-1-image.pdf ./storage/

RUN pip install --no-cache-dir .

ENV EXTRACTOR_HOST=0.0.0.0
ENV EXTRACTOR_APP_ROOT=/app

# Render and other PaaS hosts inject PORT at runtime; local default is 8000.
EXPOSE 8000

# Provide OPENROUTER_API_KEY (or ANTHROPIC_API_KEY) at runtime.
CMD ["extractor", "serve"]
