"""API contract tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from extractor.api import app
from extractor.types import ExtractionResult, UsageSummary


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_health(client: TestClient) -> None:
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert "llm_configured" in body
    assert "llm_provider" in body


def test_list_models_openrouter(client: TestClient) -> None:
    res = client.get("/v1/models")
    assert res.status_code == 200
    body = res.json()
    ids = {m["id"] for m in body["models"]}
    assert "kimi-k2.6" in ids or "claude-haiku-4-5-20251001" in ids


def test_get_job_not_found(client: TestClient) -> None:
    res = client.get("/v1/jobs/does-not-exist")
    assert res.status_code == 404


@patch("extractor.api.run_extraction", new_callable=AsyncMock)
def test_extract_sync(mock_run: AsyncMock, client: TestClient, tmp_path) -> None:
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%EOF")

    mock_run.return_value = ExtractionResult(
        status="success",
        data={"invoice_number": "X"},
        usage=UsageSummary.empty(),
        job_id="abc",
    )

    with pdf.open("rb") as f:
        res = client.post(
            "/v1/extract",
            files={"file": ("test.pdf", f, "application/pdf")},
            data={"field_spec": '{"fields":[{"name":"invoice_number","label":"No","type":"string"}]}'},
        )
    assert res.status_code == 200
    assert res.json()["status"] == "success"
    mock_run.assert_awaited_once()
