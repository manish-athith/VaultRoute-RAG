import asyncio
import logging
import time
from typing import Any

from qdrant_client import AsyncQdrantClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from vaultroute_rag.core.config import Settings

logger = logging.getLogger(__name__)


class HealthService:
    """Check and close external dependencies owned by the application."""

    def __init__(self, settings: Settings, engine: AsyncEngine | None = None) -> None:
        self._timeout = settings.dependency_timeout_seconds
        self._owns_engine = engine is None
        self._engine: AsyncEngine = engine or create_async_engine(
            settings.database_url, pool_pre_ping=True
        )
        self._qdrant = AsyncQdrantClient(
            url=settings.qdrant_url,
            timeout=self._timeout,
            check_compatibility=False,
        )

    async def check_all(self) -> dict[str, dict[str, Any]]:
        postgres, qdrant = await asyncio.gather(
            self._run_with_timeout("postgres", self._check_postgres),
            self._run_with_timeout("qdrant", self._check_qdrant),
        )
        return {"postgres": postgres, "qdrant": qdrant}

    async def _run_with_timeout(self, name: str, check: Any) -> dict[str, Any]:
        started_at = time.perf_counter()
        try:
            await asyncio.wait_for(check(), timeout=self._timeout)
            return {
                "status": "up",
                "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
            }
        except Exception as exc:
            logger.warning(
                "dependency_unavailable",
                extra={"dependency": name, "error_type": type(exc).__name__},
            )
            return {
                "status": "down",
                "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
                "error": type(exc).__name__,
            }

    async def _check_postgres(self) -> None:
        async with self._engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def _check_qdrant(self) -> None:
        await self._qdrant.get_collections()

    async def close(self) -> None:
        await self._qdrant.close()
        if self._owns_engine:
            await self._engine.dispose()
