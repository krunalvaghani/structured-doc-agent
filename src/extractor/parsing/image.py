"""Image file utilities."""

from __future__ import annotations

from pathlib import Path

SUPPORTED_IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "webp", "tif", "tiff", "gif"})

_MAGIC = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
    b"RIFF": "image/webp",  # WEBP has RIFF....WEBP
}


def is_image_path(path: Path) -> bool:
    return path.suffix.lower().lstrip(".") in SUPPORTED_IMAGE_EXTENSIONS


def read_image_bytes(path: Path) -> bytes:
    return path.read_bytes()


def guess_image_mime(path: Path) -> str:
    header = path.read_bytes()[:12]
    for magic, mime in _MAGIC.items():
        if header.startswith(magic):
            if mime == "image/webp" and b"WEBP" not in header:
                continue
            return mime
    ext = path.suffix.lower().lstrip(".")
    if ext in {"jpg", "jpeg"}:
        return "image/jpeg"
    if ext == "png":
        return "image/png"
    if ext == "webp":
        return "image/webp"
    if ext == "gif":
        return "image/gif"
    return "application/octet-stream"
