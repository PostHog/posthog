"""A best-effort Redis buffer of the intents that MCP agents state on their PostHog API calls.

`record_agent_intent` keeps an intent only when its request writes an activity log row, and most MCP
calls are reads. This buffer keeps a short list of the intents of each user, team and day, so the
activity summary can see what MCP users investigate.

The buffer is optional context. It can lose records, but it must never slow down or fail a request.
So the request thread does no network I/O: it only appends to a bounded in-process queue. A daemon
thread writes the queue to Redis about once a second, with short timeouts and a circuit breaker, and
refreshes the enrolled teams in the background.

Redis keys, each with a TTL of `mcp_buffer_days`:

- `as:mcp:{team_id}:{user_id}:{yyyymmdd}`: a list of the latest `mcp_calls_per_day` records.
- `as:mcp:n:{team_id}:{user_id}:{yyyymmdd}`: the count of all records of the day, trimmed or not.
- `as:mcp:dirty`: a set of `{team_id}:{user_id}` members that have new records.

A record is `ts|session_or_conversation_id|route_name|intent`, with `ts` in Unix seconds.
"""

import os
import queue
import datetime
import threading
from collections import defaultdict
from collections.abc import Callable
from time import monotonic, perf_counter, sleep

from django.conf import settings
from django.db import connections

import redis
import structlog
from prometheus_client import Counter, Histogram

from posthog.dataclasses import frozen
from posthog.redis import get_client

logger = structlog.get_logger(__name__)

QUEUE_SIZE = 10_000
INTENT_MAX_CHARS = 200
# Session ids and route names are much shorter. The cap only bounds a caller-asserted header.
_FIELD_MAX_CHARS = 100
FLUSH_INTERVAL_SECONDS = 1.0
CIRCUIT_OPEN_SECONDS = 30.0
SETTINGS_REFRESH_SECONDS = 300.0
# The default client timeouts can stall the flush thread for seconds.
REDIS_TIMEOUT_SECONDS = 0.05
DIRTY_KEY = "as:mcp:dirty"

RECORDS = Counter(
    "activity_summary_mcp_intent_records",
    "MCP intent records by outcome: enqueued, flushed, or dropped and why.",
    ["outcome"],
)
FLUSH_SECONDS = Histogram(
    "activity_summary_mcp_intent_flush_seconds",
    "Wall-clock time of one Redis flush of the MCP intent buffer.",
    buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1),
)


def records_key(team_id: int, user_id: int, day: str) -> str:
    return f"as:mcp:{team_id}:{user_id}:{day}"


def count_key(team_id: int, user_id: int, day: str) -> str:
    return f"as:mcp:n:{team_id}:{user_id}:{day}"


@frozen
class McpIntentRecord:
    team_id: int
    user_id: int
    day: str
    value: str


@frozen
class BufferSettings:
    team_ids: frozenset[int] = frozenset()
    calls_per_day: int = 50
    buffer_days: int = 10


def _field(value: str | None, max_chars: int) -> str:
    # `|` separates the fields, and a record is one line.
    return " ".join((value or "").replace("|", " ").split())[:max_chars]


def build_record(
    *, team_id: int, user_id: int, session_id: str | None, route_name: str | None, intent: str, at: datetime.datetime
) -> McpIntentRecord:
    value = "|".join(
        (
            str(int(at.timestamp())),
            _field(session_id, _FIELD_MAX_CHARS),
            _field(route_name, _FIELD_MAX_CHARS),
            _field(intent, INTENT_MAX_CHARS),
        )
    )
    return McpIntentRecord(
        team_id=team_id, user_id=user_id, day=at.astimezone(datetime.UTC).strftime("%Y%m%d"), value=value
    )


def load_settings() -> BufferSettings:
    """The enrolled teams and the buffer limits, from the `activity-summary` flag payload and Postgres."""
    # Both modules import models and the flag harness, which the middleware import path does not need.
    from products.signals.backend.activity_summary.config import (  # noqa: PLC0415 — keeps heavy deps off the middleware import path
        ACTIVITY_SUMMARY_FLAG,
        ACTIVITY_SUMMARY_FLAG_DISTINCT_ID,
        parse_config,
    )
    from products.signals.backend.activity_summary.queue import (  # noqa: PLC0415 — keeps heavy deps off the middleware import path
        mcp_buffer_team_ids,
    )
    from products.signals.backend.scout_harness.team_limits import (  # noqa: PLC0415 — keeps heavy deps off the middleware import path
        read_flag_payload,
    )

    # Not `read_config`, which logs on every read: each web process refreshes every few minutes.
    config = parse_config(read_flag_payload(ACTIVITY_SUMMARY_FLAG, ACTIVITY_SUMMARY_FLAG_DISTINCT_ID))
    return BufferSettings(
        team_ids=frozenset(mcp_buffer_team_ids(config)),
        calls_per_day=config.mcp_calls_per_day,
        buffer_days=config.mcp_buffer_days,
    )


def _redis_client() -> redis.Redis:
    return get_client(
        settings.ACTIVITY_SUMMARY_MCP_BUFFER_REDIS_URL or None,
        socket_timeout=REDIS_TIMEOUT_SECONDS,
        socket_connect_timeout=REDIS_TIMEOUT_SECONDS,
    )


class McpIntentBuffer:
    def __init__(
        self,
        *,
        queue_size: int = QUEUE_SIZE,
        redis_client: Callable[[], redis.Redis] = _redis_client,
        clock: Callable[[], float] = monotonic,
        start_thread: bool = True,
    ) -> None:
        self._queue_size = queue_size
        self._redis_client = redis_client
        self._clock = clock
        self._start_thread = start_thread
        self._lock = threading.Lock()
        self.buffer_settings = BufferSettings()
        self._circuit_open_until = 0.0
        self._reset()

    def _reset(self) -> None:
        # A forked process inherits the queue but not the thread that drains it.
        self._pid = os.getpid()
        self._queue: queue.Queue[McpIntentRecord] = queue.Queue(maxsize=self._queue_size)
        self._thread: threading.Thread | None = None

    def append(
        self, *, team_id: int, user_id: int, session_id: str | None, route_name: str | None, intent: str
    ) -> None:
        """Queue one record for the next flush. Runs on the request thread, so it does no network I/O."""
        self._ensure_thread()
        if team_id not in self.buffer_settings.team_ids:
            return
        record = build_record(
            team_id=team_id,
            user_id=user_id,
            session_id=session_id,
            route_name=route_name,
            intent=intent,
            at=datetime.datetime.now(datetime.UTC),
        )
        try:
            self._queue.put_nowait(record)
        except queue.Full:
            RECORDS.labels(outcome="dropped_queue_full").inc()
            return
        RECORDS.labels(outcome="enqueued").inc()

    def _ensure_thread(self) -> None:
        thread = self._thread
        if self._pid == os.getpid() and thread is not None and thread.is_alive():
            return
        if not self._start_thread:
            return
        with self._lock:
            if self._pid != os.getpid():
                self._reset()
            if self._thread is not None:
                if self._thread.is_alive():
                    return
                logger.warning("activity_summary.mcp_buffer_thread_restarted")
            self._thread = threading.Thread(target=self._run, name="activity-summary-mcp-buffer", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        next_refresh_at = 0.0
        while True:
            try:
                if self._clock() >= next_refresh_at:
                    next_refresh_at = self._clock() + SETTINGS_REFRESH_SECONDS
                    try:
                        self.refresh_settings()
                    finally:
                        # This thread owns its own connection, and an idle one would stay open between refreshes.
                        connections.close_all()
                self.flush()
            except Exception:
                logger.exception("activity_summary.mcp_buffer_loop_failed")
            sleep(FLUSH_INTERVAL_SECONDS)

    def refresh_settings(self) -> None:
        try:
            self.buffer_settings = load_settings()
        except Exception:
            # Keep the last settings until the next refresh.
            logger.warning("activity_summary.mcp_buffer_settings_failed", exc_info=True)

    def _drain(self) -> list[McpIntentRecord]:
        records: list[McpIntentRecord] = []
        while True:
            try:
                records.append(self._queue.get_nowait())
            except queue.Empty:
                return records

    def flush(self) -> None:
        """Write the queued records to Redis in one pipeline, or drop them while the circuit is open."""
        records = self._drain()
        if not records:
            return
        if self._clock() < self._circuit_open_until:
            RECORDS.labels(outcome="dropped_circuit_open").inc(len(records))
            return
        started = perf_counter()
        try:
            self._write(records, self.buffer_settings)
        except Exception:
            self._circuit_open_until = self._clock() + CIRCUIT_OPEN_SECONDS
            RECORDS.labels(outcome="dropped_flush_error").inc(len(records))
            logger.warning("activity_summary.mcp_buffer_flush_failed", records=len(records), exc_info=True)
            return
        finally:
            FLUSH_SECONDS.observe(perf_counter() - started)
        RECORDS.labels(outcome="flushed").inc(len(records))

    def _write(self, records: list[McpIntentRecord], buffer_settings: BufferSettings) -> None:
        ttl = int(datetime.timedelta(days=buffer_settings.buffer_days).total_seconds())
        grouped: dict[tuple[int, int, str], list[str]] = defaultdict(list)
        for record in records:
            grouped[(record.team_id, record.user_id, record.day)].append(record.value)
        pipeline = self._redis_client().pipeline(transaction=False)
        for (team_id, user_id, day), values in grouped.items():
            key = records_key(team_id, user_id, day)
            pipeline.rpush(key, *values)
            pipeline.ltrim(key, -buffer_settings.calls_per_day, -1)
            pipeline.expire(key, ttl)
            pipeline.incrby(count_key(team_id, user_id, day), len(values))
            pipeline.expire(count_key(team_id, user_id, day), ttl)
            pipeline.sadd(DIRTY_KEY, f"{team_id}:{user_id}")
        # Without a TTL the set would outlive a disabled buffer.
        pipeline.expire(DIRTY_KEY, ttl)
        pipeline.execute()


BUFFER = McpIntentBuffer()
