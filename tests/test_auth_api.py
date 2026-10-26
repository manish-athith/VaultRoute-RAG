from fastapi.testclient import TestClient


def test_login_payload_is_validated_before_database_access(client: TestClient) -> None:
    response = client.post(
        "/auth/login",
        json={"company_slug": "acme", "email": "not-an-email", "password": "short"},
    )

    assert response.status_code == 422


def test_current_user_requires_bearer_token(client: TestClient) -> None:
    response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
