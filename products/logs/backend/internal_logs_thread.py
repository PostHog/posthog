import os
import sys
import time
import asyncio
import threading
from collections.abc import Callable

import structlog

from posthog.models.team import Team
from posthog.sync import database_sync_to_async_pool

from products.logs.backend.internal_logs_producer import (
    RECORDS_COUNTER,
    InternalLogEntry,
    InternalLogsProducer,
    InternalLogsProducerConfig,
)

logger = structlog.get_logger(__name__)

# Shorter than LOGS_INTERNAL_PRODUCER_RETRY_TIMEOUT_MS, so a capture-logs outage does not hold a worker's exit.
# The exit wait also stays under the dev server's 5 second `--workers-kill-timeout` (bin/start-backend).
DRAIN_TIMEOUT_SECONDS = 3
EXIT_WAIT_SECONDS = DRAIN_TIMEOUT_SECONDS + 1

TOKEN_CACHE_TTL_SECONDS = 300
_MAX_CACHED_TEAMS = 10_000
_PENDING_ENTRY_OVERHEAD_BYTES = 1024

_lock = threading.Lock()
_pid: int | None = None
_producer: InternalLogsProducer | None = None
_loop: asyncio.AbstractEventLoop | None = None
_max_pending_bytes = 0
_pending_bytes = 0
_token_lock = threading.Lock()
_token_cache: dict[int, tuple[float, str]] = {}

_register_before_thread_shutdown: Callable[..., None] = vars(threading)["_register_atexit"]


def _read_api_token(team_id: int) -> str | None:
    with _token_lock:
        cached = _token_cache.get(team_id)
        if cached is not None and cached[0] > time.monotonic():
            return cached[1]

    token = Team.objects.filter(id=team_id).values_list("api_token", flat=True).first()
    if token is None:
        return None

    with _token_lock:
        if len(_token_cache) >= _MAX_CACHED_TEAMS:
            soonest_to_expire = sorted(_token_cache, key=lambda cached_id: _token_cache[cached_id][0])
            for evicted_id in soonest_to_expire[: _MAX_CACHED_TEAMS // 2]:
                del _token_cache[evicted_id]
        _token_cache[team_id] = (time.monotonic() + TOKEN_CACHE_TTL_SECONDS, token)
    return token


async def _api_token(team_id: int) -> str | None:
    return await database_sync_to_async_pool(_read_api_token)(team_id)


def _enqueue(producer: InternalLogsProducer, source: str, entries: list[InternalLogEntry], size: int) -> None:
    global _pending_bytes
    with _lock:
        _pending_bytes -= size
    producer.enqueue(source, entries)
    producer.flush()


def _drain(pid: int, producer: InternalLogsProducer, loop: asyncio.AbstractEventLoop) -> None:
    # A forked child inherits this exit handler, but not the thread that runs the loop.
    if pid != os.getpid():
        return
    try:
        asyncio.run_coroutine_threadsafe(producer.drain(DRAIN_TIMEOUT_SECONDS), loop).result(EXIT_WAIT_SECONDS)
    except Exception:
        logger.warning("Failed to drain the internal logs producer at exit", exc_info=True)


def send_internal_logs(source: str, entries: list[InternalLogEntry]) -> None:
    """Hands the entries of allowed teams to this process's producer. Does not wait for the network."""
    global _pid, _producer, _loop, _max_pending_bytes, _pending_bytes
    with _lock:
        if _producer is None or _pid != os.getpid():
            config = InternalLogsProducerConfig.from_settings()
            _producer = InternalLogsProducer(config, _api_token)
            _loop = None
            _pid = os.getpid()
            _max_pending_bytes = config.max_buffered_bytes
            _pending_bytes = 0
        producer = _producer
        entries = [entry for entry in entries if producer.accepts(source, entry.team_id)]
        if not entries:
            return
        size = sum(sys.getsizeof(entry.message) + _PENDING_ENTRY_OVERHEAD_BYTES for entry in entries)
        if _pending_bytes + size > _max_pending_bytes:
            RECORDS_COUNTER.labels(source=source, outcome="dropped").inc(len(entries))
            return
        if _loop is None:
            new_loop = asyncio.new_event_loop()
            try:
                threading.Thread(target=new_loop.run_forever, name="internal-logs-producer", daemon=True).start()
            except BaseException:
                new_loop.close()
                raise
            _loop = new_loop
            # Not `atexit`, because those handlers run after the interpreter stops every thread pool, and the
            # producer needs one to read the team token and to resolve the capture-logs host.
            _register_before_thread_shutdown(_drain, _pid, producer, _loop)
        _pending_bytes += size
        loop = _loop
    loop.call_soon_threadsafe(_enqueue, producer, source, entries, size)
