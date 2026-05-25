"""Rate limit and quota API tests."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from extractor.api import app
from extractor.rate_limit import reset_rate_limiter_for_tests
from extractor.types import ExtractionResult, UsageSummary


@pytest.fixture(autouse=True)
def _reset_limiter() -> None:
    reset_rate_limiter_for_tests()
    yield
    reset_rate_limiter_for_tests()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def field_spec_data() -> dict[str, str]:
    return {
        "field_spec": '{"fields":[{"name":"invoice_number","label":"No","type":"string"}]}'
    }


@pytest.fixture
def tiny_pdf(tmp_path):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF")
    return pdf


def test_quota_disabled_by_default(client: TestClient) -> None:
    res = client.get("/v1/quota")
    assert res.status_code == 200
    assert res.json()["enabled"] is False


@patch("extractor.api.run_extraction", new_callable=AsyncMock)
def test_extract_unlimited_when_disabled(
    mock_run: AsyncMock,
    client: TestClient,
    tiny_pdf,
    field_spec_data: dict[str, str],
) -> None:
    mock_run.return_value = ExtractionResult(
        status="success",
        data={"invoice_number": "X"},
        usage=UsageSummary.empty(),
        job_id="abc",
    )
    with patch.dict(os.environ, {"EXTRACTOR_RATE_LIMIT_ENABLED": "false"}, clear=False):
        reset_rate_limiter_for_tests()
        for _ in range(3):
            with tiny_pdf.open("rb") as f:
                res = client.post(
                    "/v1/extract",
                    files={"file": ("test.pdf", f, "application/pdf")},
                    data=field_spec_data,
                )
            assert res.status_code == 200


@patch("extractor.api.run_extraction", new_callable=AsyncMock)
def test_per_ip_limit_returns_429(
    mock_run: AsyncMock,
    client: TestClient,
    tiny_pdf,
    field_spec_data: dict[str, str],
) -> None:
    mock_run.return_value = ExtractionResult(
        status="success",
        data={"invoice_number": "X"},
        usage=UsageSummary.empty(),
        job_id="abc",
    )
    env = {
        "EXTRACTOR_RATE_LIMIT_ENABLED": "true",
        "EXTRACTOR_RATE_LIMIT_PER_IP": "5",
        "EXTRACTOR_RATE_LIMIT_GLOBAL_DAILY": "100",
    }
    with patch.dict(os.environ, env, clear=False):
        reset_rate_limiter_for_tests()
        headers = {"X-Forwarded-For": "203.0.113.10"}
        for i in range(5):
            with tiny_pdf.open("rb") as f:
                res = client.post(
                    "/v1/extract",
                    files={"file": ("test.pdf", f, "application/pdf")},
                    data=field_spec_data,
                    headers=headers,
                )
            assert res.status_code == 200, f"request {i + 1} failed"

        with tiny_pdf.open("rb") as f:
            res = client.post(
                "/v1/extract",
                files={"file": ("test.pdf", f, "application/pdf")},
                data=field_spec_data,
                headers=headers,
            )
        assert res.status_code == 429
        body = res.json()["detail"]
        assert body["error"] == "rate_limit_exceeded"
        assert body["scope"] == "ip"
        assert "quota" in body
        assert mock_run.await_count == 5


@patch("extractor.api.run_extraction", new_callable=AsyncMock)
def test_global_daily_limit_returns_429(
    mock_run: AsyncMock,
    client: TestClient,
    tiny_pdf,
    field_spec_data: dict[str, str],
) -> None:
    mock_run.return_value = ExtractionResult(
        status="success",
        data={"invoice_number": "X"},
        usage=UsageSummary.empty(),
        job_id="abc",
    )
    env = {
        "EXTRACTOR_RATE_LIMIT_ENABLED": "true",
        "EXTRACTOR_RATE_LIMIT_PER_IP": "100",
        "EXTRACTOR_RATE_LIMIT_GLOBAL_DAILY": "20",
    }
    with patch.dict(os.environ, env, clear=False):
        reset_rate_limiter_for_tests()
        for i in range(20):
            ip = f"198.51.100.{i + 1}"
            with tiny_pdf.open("rb") as f:
                res = client.post(
                    "/v1/extract",
                    files={"file": ("test.pdf", f, "application/pdf")},
                    data=field_spec_data,
                    headers={"X-Forwarded-For": ip},
                )
            assert res.status_code == 200

        with tiny_pdf.open("rb") as f:
            res = client.post(
                "/v1/extract",
                files={"file": ("test.pdf", f, "application/pdf")},
                data=field_spec_data,
                headers={"X-Forwarded-For": "198.51.100.99"},
            )
        assert res.status_code == 429
        assert res.json()["detail"]["scope"] == "global"


def test_quota_snapshot_when_enabled(client: TestClient) -> None:
    env = {
        "EXTRACTOR_RATE_LIMIT_ENABLED": "true",
        "EXTRACTOR_RATE_LIMIT_PER_IP": "5",
        "EXTRACTOR_RATE_LIMIT_GLOBAL_DAILY": "20",
    }
    with patch.dict(os.environ, env, clear=False):
        reset_rate_limiter_for_tests()
        res = client.get("/v1/quota", headers={"X-Forwarded-For": "203.0.113.5"})
        assert res.status_code == 200
        body = res.json()
        assert body["enabled"] is True
        assert body["remaining_ip"] == 5
        assert body["limit_ip"] == 5
        assert body["remaining_global"] == 20
        assert body["limit_global_daily"] == 20


def test_health_includes_rate_limit_flag(client: TestClient) -> None:
    res = client.get("/health")
    assert res.status_code == 200
    assert "rate_limit_enabled" in res.json()
