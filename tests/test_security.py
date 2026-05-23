"""Security path guard tests."""

from __future__ import annotations

import pytest

from extractor.security import PathGuard


def test_path_guard_allows_inside_root(tmp_path) -> None:
    root = tmp_path / "job"
    root.mkdir()
    doc = root / "doc.pdf"
    doc.write_bytes(b"%PDF-1.4")
    guard = PathGuard(root)
    assert guard.resolve_allowed(doc) == doc.resolve()


def test_path_guard_rejects_outside_root(tmp_path) -> None:
    root = tmp_path / "job"
    root.mkdir()
    outside = tmp_path / "other.pdf"
    outside.write_bytes(b"%PDF-1.4")
    guard = PathGuard(root)
    with pytest.raises(PermissionError):
        guard.resolve_allowed(outside)
