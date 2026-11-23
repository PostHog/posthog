"""Sends internal logs from sync code, such as a web request thread, on one background event loop per process."""

import os
import asyncio
import threading

import structlog

from posthog.sync import database_sync_to_async_pool

from products.logs.backend.internal_logs_producer import (
    InternalLogEntry,
    InternalLogsProducer,
    InternalLogsProducerConfig,
)

logger = structlog.get_logger(__name__)

# Shorter than LOGS_INTERNAL_PRODUCER_RETRY_TIMEOUT_MS, because the web server kills a worker that takes too long
# to exit, and a capture-logs outage must not hold every worker until that kill.
DRAIN_TIMEOUT_SECONDS = 5

_lock = threading.Lock()
_pid: int | None = None
_producer: InternalLogsProducer | None = None
_loop: asyncio.AbstractEventLoop | None = None


def _read_api_token(team_id: int) -> str | None:
    from posthog.models.team import (
        Team,  # noqa: PLC0415 -- the facade imports this module before the app registry is ready
    )

    # shortcut: one Postgres read for each request to capture-logs, add a cache when a high-volume source uses this
    return Team.objects.filter(id=team_id).values_list("api_token", flat=True).first()


async def _api_token(team_id: int) -> str | None:
    return await database_sync_to_async_pool(_read_api_token)(team_id)


def _enqueue(producer: InternalLogsProducer, source: str, entries: list[InternalLogEntry]) -> None:
    producer.enqueue(source, entries)
    producer.flush()


def _drain(pid: int, producer: InternalLogsProducer, loop: asyncio.AbstractEventLoop) -> None:
    # A forked child inherits this exit handler, but not the thread that runs the loop.
    if pid != os.getpid():
        return
    try:
        asyncio.run_coroutine_threadsafe(producer.drain(DRAIN_TIMEOUT_SECONDS), loop).result(DRAIN_TIMEOUT_SECONDS + 1)
    except Exception:
        logger.warning("Failed to drain the internal logs producer at exit", exc_info=True)


def send_internal_logs(source: str, entries: list[InternalLogEntry]) -> None:
    """Hands the entries of allowed teams to this process's producer. Does not wait for the network."""
    global _pid, _producer, _loop
    with _lock:
        if _producer is None or _pid != os.getpid():
            _producer = InternalLogsProducer(InternalLogsProducerConfig.from_settings(), _api_token)
            _loop = None
            _pid = os.getpid()
        producer = _producer
        entries = [entry for entry in entries if producer.accepts(source, entry.team_id)]
        if not entries:
            return
        if _loop is None:
            _loop = asyncio.new_event_loop()
            threading.Thread(target=_loop.run_forever, name="internal-logs-producer", daemon=True).start()
            # Not `atexit`, because those handlers run after the interpreter stops every thread pool, and the
            # producer needs one to read the team token and to resolve the capture-logs host.
            threading._register_atexit(_drain, _pid, producer, _loop)  # type: ignore[attr-defined]
        loop = _loop
    loop.call_soon_threadsafe(_enqueue, producer, source, entries)
