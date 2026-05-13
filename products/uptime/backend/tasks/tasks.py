from __future__ import annotations

import time
from uuid import UUID

from django.utils import timezone

import requests
import structlog
from celery import Task, shared_task

from .. import logic
from ..facade.enums import PingOutcome
from ..models import Monitor

logger = structlog.get_logger(__name__)

PING_TIMEOUT_SECONDS = 10
PING_MAX_RETRIES = 2  # 2 retries on top of initial attempt = 3 attempts total


class _PingHTTPError(Exception):
    def __init__(self, status_code: int, latency_ms: int) -> None:
        self.status_code = status_code
        self.latency_ms = latency_ms


@shared_task(bind=True, max_retries=PING_MAX_RETRIES, ignore_result=True)
def ping_monitor(self: Task, monitor_id: str) -> None:
    monitor = Monitor.objects.unscoped().get(id=monitor_id)
    started_at = time.perf_counter()
    status_code: int | None = None
    latency_ms: int = 0

    try:
        response = requests.get(monitor.url, timeout=PING_TIMEOUT_SECONDS)
        latency_ms = int((time.perf_counter() - started_at) * 1000)
        if response.status_code < 400:
            logic.record_ping(
                team_id=monitor.team_id,
                monitor_id=monitor.id,
                timestamp=timezone.now(),
                latency_ms=latency_ms,
                status_code=response.status_code,
                outcome=PingOutcome.SUCCESS,
            )
            return
        raise _PingHTTPError(status_code=response.status_code, latency_ms=latency_ms)
    except (requests.RequestException, _PingHTTPError) as exc:
        if isinstance(exc, _PingHTTPError):
            status_code = exc.status_code
            latency_ms = exc.latency_ms
        else:
            latency_ms = int((time.perf_counter() - started_at) * 1000)

        if self.request.retries >= PING_MAX_RETRIES:
            logic.record_ping(
                team_id=monitor.team_id,
                monitor_id=monitor.id,
                timestamp=timezone.now(),
                latency_ms=latency_ms,
                status_code=status_code,
                outcome=PingOutcome.FAILURE,
            )
            return

        raise self.retry(exc=exc, countdown=10)


@shared_task(ignore_result=True)
def ping_all_monitors() -> None:
    monitor_ids: list[UUID] = list(Monitor.objects.unscoped().values_list("id", flat=True))
    for monitor_id in monitor_ids:
        ping_monitor.delay(str(monitor_id))
