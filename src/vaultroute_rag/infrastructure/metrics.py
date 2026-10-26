import threading
import time
from collections import Counter


class RuntimeMetrics:
    """Small in-process operational counters exposed in Prometheus text format."""

    def __init__(self) -> None:
        self._started_at = time.monotonic()
        self._lock = threading.Lock()
        self._requests = 0
        self._in_flight = 0
        self._total_seconds = 0.0
        self._status_families: Counter[str] = Counter()

    def request_started(self) -> None:
        with self._lock:
            self._in_flight += 1

    def request_completed(self, status_code: int, elapsed_seconds: float) -> None:
        status_family = f"{status_code // 100}xx"
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)
            self._requests += 1
            self._total_seconds += elapsed_seconds
            self._status_families[status_family] += 1

    def render(self) -> str:
        with self._lock:
            requests = self._requests
            in_flight = self._in_flight
            total_seconds = self._total_seconds
            statuses = dict(self._status_families)
        uptime = time.monotonic() - self._started_at
        lines = [
            "# HELP vaultroute_uptime_seconds Process uptime in seconds.",
            "# TYPE vaultroute_uptime_seconds gauge",
            f"vaultroute_uptime_seconds {uptime:.3f}",
            "# HELP vaultroute_http_requests_total Completed HTTP requests.",
            "# TYPE vaultroute_http_requests_total counter",
            f"vaultroute_http_requests_total {requests}",
            "# HELP vaultroute_http_requests_in_flight Current HTTP requests.",
            "# TYPE vaultroute_http_requests_in_flight gauge",
            f"vaultroute_http_requests_in_flight {in_flight}",
            "# HELP vaultroute_http_request_duration_seconds_total Total request time.",
            "# TYPE vaultroute_http_request_duration_seconds_total counter",
            f"vaultroute_http_request_duration_seconds_total {total_seconds:.6f}",
            "# HELP vaultroute_http_responses_total Responses by status family.",
            "# TYPE vaultroute_http_responses_total counter",
        ]
        lines.extend(
            f'vaultroute_http_responses_total{{status_family="{family}"}} {count}'
            for family, count in sorted(statuses.items())
        )
        return "\n".join(lines) + "\n"
