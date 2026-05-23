"""File type detection and validation."""

from __future__ import annotations

from pathlib import Path

from extractor.parsing.image import SUPPORTED_IMAGE_EXTENSIONS

PDF_MAGIC = b"%PDF"
MAX_FILE_BYTES_DEFAULT = 25 * 1024 * 1024


def detect_kind(path: Path) -> str:
    header = path.read_bytes()[:8]
    if header.startswith(PDF_MAGIC):
        return "pdf"
    ext = path.suffix.lower().lstrip(".")
    if ext in SUPPORTED_IMAGE_EXTENSIONS:
        return "image"
    raise ValueError(f"unsupported file type: {path.suffix!r}")


def validate_file_size(path: Path, *, max_mb: int) -> None:
    size = path.stat().st_size
    limit = max_mb * 1024 * 1024
    if size > limit:
        raise ValueError(f"file exceeds {max_mb} MB limit")


def supported_extensions() -> frozenset[str]:
    return frozenset({"pdf", *SUPPORTED_IMAGE_EXTENSIONS})
