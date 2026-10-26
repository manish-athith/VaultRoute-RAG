import secrets
from typing import Any

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse, PlainTextResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def liveness(request: Request) -> dict[str, str]:
    settings = request.app.state.settings
    return {
        "status": "alive",
        "service": settings.app_name,
        "version": settings.app_version,
    }


@router.get("/ready", response_model=None)
async def readiness(request: Request) -> JSONResponse:
    checks: dict[str, dict[str, Any]] = await request.app.state.health_service.check_all()
    is_ready = all(check["status"] == "up" for check in checks.values())
    response_status = status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(
        status_code=response_status,
        content={"status": "ready" if is_ready else "not_ready", "checks": checks},
    )


@router.get("/metrics", response_model=None)
async def operational_metrics(request: Request) -> PlainTextResponse:
    configured = request.app.state.settings.metrics_bearer_token
    if configured:
        expected = configured.get_secret_value()
        authorization = request.headers.get("Authorization", "")
        scheme, _, supplied = authorization.partition(" ")
        if scheme.lower() != "bearer" or not secrets.compare_digest(supplied, expected):
            return PlainTextResponse("Unauthorized\n", status_code=status.HTTP_401_UNAUTHORIZED)
    return PlainTextResponse(
        request.app.state.runtime_metrics.render(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
