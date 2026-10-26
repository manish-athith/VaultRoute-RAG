from fastapi.testclient import TestClient


def test_request_id_is_generated(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
    assert float(response.headers["X-Process-Time-Ms"]) >= 0


def test_safe_client_request_id_is_preserved(client: TestClient) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": "demo-request-42"})

    assert response.headers["X-Request-ID"] == "demo-request-42"
