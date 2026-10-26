from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from vaultroute_rag.core.config import Settings
from vaultroute_rag.main import create_app


class FakeHealthService:
    def __init__(self, checks: dict[str, dict[str, Any]] | None = None) -> None:
        self._checks = checks or {
            "postgres": {"status": "up", "latency_ms": 1.0},
            "qdrant": {"status": "up", "latency_ms": 1.0},
        }

    async def check_all(self) -> dict[str, dict[str, Any]]:
        return self._checks

    async def close(self) -> None:
        return None


def build_client(
    checks: dict[str, dict[str, Any]] | None = None,
) -> TestClient:
    settings = Settings(
        app_name="VaultRoute Test",
        app_version="test",
        database_url="postgresql+asyncpg://unused:unused@localhost:5432/unused",
        qdrant_url="http://localhost:6333",
    )
    return TestClient(create_app(settings=settings, health_service=FakeHealthService(checks)))


@pytest.fixture
def client() -> Iterator[TestClient]:
    with build_client() as test_client:
        yield test_client
