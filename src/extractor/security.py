"""Path guards for job-scoped document access."""

from __future__ import annotations

from pathlib import Path


class PathGuard:
    def __init__(self, allowed_root: Path) -> None:
        self.allowed_root = allowed_root.resolve()

    def resolve_allowed(self, path: str | Path) -> Path:
        candidate = Path(path).resolve()
        try:
            candidate.relative_to(self.allowed_root)
        except ValueError as exc:
            raise PermissionError(
                f"access denied: {candidate} is outside {self.allowed_root}"
            ) from exc
        if not candidate.is_file():
            raise FileNotFoundError(f"document not found: {candidate}")
        return candidate
