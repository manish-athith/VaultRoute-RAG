from fastapi.testclient import TestClient

from tests.conftest import build_client


def test_liveness(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "status": "alive",
        "service": "VaultRoute Test",
        "version": "test",
    }


def test_readiness_when_dependencies_are_available(client: TestClient) -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_readiness_when_a_dependency_is_unavailable() -> None:
    checks = {
        "postgres": {"status": "up", "latency_ms": 1.0},
        "qdrant": {"status": "down", "latency_ms": 1.0, "error": "TimeoutError"},
    }

    with build_client(checks) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"]["qdrant"]["status"] == "down"
