import logging
import time
import uuid
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from vaultroute_rag.core.logging import request_id_context

logger = logging.getLogger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request ID and elapsed-time information to every request."""

    async def dispatch(self, request: Request, call_next) -> Response:
        supplied_request_id = request.headers.get("X-Request-ID", "").strip()
        request_id = supplied_request_id[:128] if supplied_request_id else str(uuid.uuid4())
        token = request_id_context.set(request_id)
        started_at = time.perf_counter()
        metrics = getattr(request.app.state, "runtime_metrics", None)
        if metrics is not None:
            metrics.request_started()

        try:
            response = await call_next(request)
            elapsed_seconds = time.perf_counter() - started_at
            elapsed_ms = elapsed_seconds * 1000
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Process-Time-Ms"] = f"{elapsed_ms:.2f}"
            if metrics is not None:
                metrics.request_completed(response.status_code, elapsed_seconds)
            logger.info(
                "request_completed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "elapsed_ms": round(elapsed_ms, 2),
                },
            )
            return response
        finally:
            request_id_context.reset(token)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add browser defenses without changing API behavior."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; "
            "form-action 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        )
        if not request.url.path.startswith("/assets/"):
            response.headers["Cache-Control"] = "no-store"
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-process IP throttling for abuse control; use a shared gateway at larger scale."""

    def __init__(
        self,
        app,
        *,
        default_limit: int,
        login_limit: int,
        query_limit: int,
        upload_limit: int,
    ) -> None:
        super().__init__(app)
        self._limits = {
            "default": default_limit,
            "login": login_limit,
            "query": query_limit,
            "upload": upload_limit,
        }
        self._events: defaultdict[tuple[str, str], deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path.startswith(("/assets/", "/health/")) or request.url.path == "/":
            return await call_next(request)

        bucket = self._bucket(request)
        limit = self._limits[bucket]
        client_ip = request.client.host if request.client else "unknown"
        key = (client_ip, bucket)
        now = time.monotonic()
        cutoff = now - 60
        events = self._events[key]
        while events and events[0] <= cutoff:
            events.popleft()
        if len(events) >= limit:
            retry_after = max(1, int(60 - (now - events[0])))
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests; please retry shortly"},
                headers={"Retry-After": str(retry_after)},
            )
        events.append(now)
        return await call_next(request)

    @staticmethod
    def _bucket(request: Request) -> str:
        path = request.url.path
        if request.method == "POST" and path == "/auth/login":
            return "login"
        if request.method == "POST" and path in {"/query", "/search"}:
            return "query"
        if request.method == "POST" and path == "/documents/upload":
            return "upload"
        return "default"
