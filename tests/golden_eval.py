"""Assert extraction output against golden fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
BOTTLES_CI_GOLDEN_PATH = FIXTURES_DIR / "bottles_ci_expected.json"


def load_bottles_ci_golden() -> dict[str, Any]:
    return json.loads(BOTTLES_CI_GOLDEN_PATH.read_text())


def _find_line_item(items: list[Any], item_code: str) -> dict[str, Any] | None:
    for row in items:
        if isinstance(row, dict) and row.get("item_code") == item_code:
            return row
    return None


def _approx_equal(actual: Any, expected: float, *, tol: float = 0.02) -> bool:
    try:
        return abs(float(actual) - float(expected)) <= tol
    except (TypeError, ValueError):
        return False


def assert_bottles_ci_extraction(data: dict[str, Any] | None) -> list[str]:
    """Return human-readable assertion failures (empty list = pass)."""
    if data is None:
        return ["data is None"]

    golden = load_bottles_ci_golden()
    expected = golden["data"]
    failures: list[str] = []

    invoice = data.get("invoice_number")
    if invoice != expected["invoice_number"]:
        failures.append(
            f"invoice_number: expected {expected['invoice_number']!r}, got {invoice!r}"
        )

    total = data.get("total_amount_usd")
    if not _approx_equal(total, expected["total_amount_usd"], tol=1.0):
        failures.append(
            f"total_amount_usd: expected ~{expected['total_amount_usd']}, got {total!r}"
        )

    line_items = data.get("line_items")
    if not isinstance(line_items, list):
        failures.append(f"line_items: expected list, got {type(line_items).__name__}")
        return failures

    expected_count = expected["line_items_count"]
    if len(line_items) != expected_count:
        failures.append(
            f"line_items count: expected {expected_count}, got {len(line_items)}"
        )

    codes = {row.get("item_code") for row in line_items if isinstance(row, dict)}
    for code in expected.get("line_items_must_include_codes", []):
        if code not in codes:
            failures.append(f"line_items missing item_code {code!r}")

    for sample in expected.get("line_items_sample", []):
        code = sample["item_code"]
        row = _find_line_item(line_items, code)
        if row is None:
            failures.append(f"line_items missing sample row {code!r}")
            continue
        desc = row.get("description") or ""
        needle = sample.get("description_contains", "")
        if needle and needle.lower() not in str(desc).lower():
            failures.append(
                f"{code} description: expected to contain {needle!r}, got {desc!r}"
            )
        for field in ("quantity", "hs_code"):
            if field in sample and row.get(field) != sample[field]:
                failures.append(
                    f"{code} {field}: expected {sample[field]!r}, got {row.get(field)!r}"
                )
        for field in ("unit_price_usd", "total_amount_usd"):
            if field in sample and not _approx_equal(row.get(field), sample[field]):
                failures.append(
                    f"{code} {field}: expected ~{sample[field]}, got {row.get(field)!r}"
                )

    return failures
