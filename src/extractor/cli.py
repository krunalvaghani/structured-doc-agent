#!/usr/bin/env python3
"""CLI for document extraction."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from extractor.config import get_settings
from extractor.cost import format_cost_line
from extractor.events import ProgressEmitter
from extractor.logger import configure_logging, get_logger
from extractor.runner import parse_field_spec_json, run_extraction
from extractor.types import ExtractionOptions, ExtractionRequest

load_dotenv()
log = get_logger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract structured data from documents.")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run extraction on a local file")
    run.add_argument("--file", required=True, help="Path to PDF or image")
    run.add_argument("--field-spec", help="Path to field spec JSON")
    run.add_argument("--prompt", help="Natural language extraction prompt")
    run.add_argument("--schema", help="Path to JSON Schema file")
    run.add_argument("--model", help="Extraction model override")
    run.add_argument("--schema-model", help="Schema planner model override")
    run.add_argument("--output", "-o", help="Write result JSON to file")
    run.add_argument("--verbose", action="store_true")
    run.add_argument("--backend", choices=["agent", "api"], help="Extraction backend override")

    serve = sub.add_parser("serve", help="Start API server and demo UI")
    serve.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    serve.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    serve.add_argument("--reload", action="store_true", help="Auto-reload on code changes")
    return parser


def _serve_cli(args: argparse.Namespace) -> int:
    import uvicorn

    configure_logging(level="INFO")
    log.info("starting server http://%s:%s/ui", args.host, args.port)
    print(f"Extractor API: http://{args.host}:{args.port}", file=sys.stderr)
    print(f"Demo UI:       http://{args.host}:{args.port}/ui", file=sys.stderr)
    print(f"Health:        http://{args.host}:{args.port}/health", file=sys.stderr)
    uvicorn.run(
        "extractor.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


async def _run_cli(args: argparse.Namespace) -> int:
    configure_logging(level="DEBUG" if args.verbose else "INFO", force=args.verbose)
    settings = get_settings()

    path = Path(args.file)
    if not path.is_file():
        log.error("file not found: %s", path)
        return 2

    req = ExtractionRequest(
        document_path=path,
        options=ExtractionOptions(
            model=args.model,
            schema_model=args.schema_model,
            backend=args.backend,
        ),
    )
    if args.field_spec:
        req.field_spec = parse_field_spec_json(json.loads(Path(args.field_spec).read_text()))
    elif args.prompt:
        req.prompt = args.prompt
    elif args.schema:
        req.schema = json.loads(Path(args.schema).read_text())
    else:
        log.error("provide one of --field-spec, --prompt, or --schema")
        return 2

    emitter = ProgressEmitter()

    async def consume() -> None:
        async for event in emitter.subscribe():
            if not args.quiet:
                print(f"[{event.source}] {event.message}", file=sys.stderr)

    import asyncio

    consumer = asyncio.create_task(consume())
    try:
        result = await run_extraction(req, settings=settings, emitter=emitter)
    finally:
        await consumer

    payload = json.dumps(result.to_dict(), indent=2)
    if args.output:
        Path(args.output).write_text(payload + "\n")
    else:
        print(payload)

    if not args.quiet:
        print(format_cost_line(result.usage), file=sys.stderr)

    return 0 if result.status == "success" else 1


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        import asyncio

        return asyncio.run(_run_cli(args))
    if args.command == "serve":
        return _serve_cli(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
