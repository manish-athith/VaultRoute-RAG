import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from tests.conftest import FakeHealthService
from vaultroute_rag.core.config import Settings
from vaultroute_rag.main import create_app


def hardened_client(**overrides) -> TestClient:
    settings = Settings(
        app_name="VaultRoute Test",
        app_version="test",
        database_url="postgresql+asyncpg://unused:unused@localhost:5432/unused",
        qdrant_url="http://localhost:6333",
        **overrides,
    )
    return TestClient(create_app(settings=settings, health_service=FakeHealthService()))


def test_portal_and_static_assets_are_served_with_security_headers() -> None:
    with hardened_client() as client:
        portal = client.get("/")
        script = client.get("/assets/app.js")

    assert portal.status_code == 200
    assert "VaultRoute" in portal.text
    assert script.status_code == 200
    assert "renderSafeMarkdown" in script.text
    assert "innerHTML" not in script.text
    assert portal.headers["x-frame-options"] == "DENY"
    assert portal.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in portal.headers["content-security-policy"]
    assert portal.headers["cache-control"] == "no-store"


def test_sensitive_route_rate_limit_returns_retry_after() -> None:
    with hardened_client(rate_limit_login_per_minute=2) as client:
        first = client.post("/auth/login", json={})
        second = client.post("/auth/login", json={})
        limited = client.post("/auth/login", json={})

    assert first.status_code == 422
    assert second.status_code == 422
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) >= 1
    assert limited.headers["x-frame-options"] == "DENY"


def test_operational_metrics_can_require_a_bearer_token() -> None:
    with hardened_client(metrics_bearer_token="a-strong-monitoring-token") as client:
        denied = client.get("/health/metrics")
        allowed = client.get(
            "/health/metrics",
            headers={"Authorization": "Bearer a-strong-monitoring-token"},
        )

    assert denied.status_code == 401
    assert allowed.status_code == 200
    assert "vaultroute_http_requests_total" in allowed.text
    assert "vaultroute_http_request_duration_seconds_total" in allowed.text


def test_production_rejects_unsafe_secrets_and_wildcard_hosts() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(environment="production")

    with pytest.raises(ValidationError, match="ALLOWED_HOSTS"):
        Settings(
            environment="production",
            jwt_secret_key="j" * 32,
            metrics_bearer_token="m" * 24,
            allowed_hosts="*",
        )

    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(_env_file=".env.production.example")


def test_api_docs_can_be_disabled() -> None:
    with hardened_client(enable_api_docs=False) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404


def test_unknown_host_is_rejected() -> None:
    with hardened_client() as client:
        response = client.get("/health/live", headers={"Host": "attacker.invalid"})

    assert response.status_code == 400
