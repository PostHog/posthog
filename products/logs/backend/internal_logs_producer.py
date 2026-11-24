"""Sends internal logs to capture-logs. A port of nodejs/src/logs/internal-logs-producer.ts."""

import json
import time
import random
import asyncio
import functools
import dataclasses
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime
from typing import Any, Literal

from django.conf import settings

import aiohttp
import structlog
from prometheus_client import Counter, Gauge

from posthog.dataclasses import frozen

from products.logs.backend.internal_logs import (
    INTERNAL_LOGS_HTTP_HEADER,
    INTERNAL_SOURCE_SERVICE_NAMES,
    sign_internal_logs,
)

logger = structlog.get_logger(__name__)

SEVERITY_NUMBERS: dict[str, int] = {"debug": 5, "info": 9, "warn": 13, "error": 17}

# Half of capture-logs' default 2 MiB body limit, which leaves room for the envelope.
MAX_REQUEST_RECORD_BYTES = 1024 * 1024

# A JSON-escaped code point takes at most 6 bytes, so a message cut to this length always fits in one request.
MAX_MESSAGE_LENGTH = 128 * 1024

# The librdkafka default request.timeout.ms, and above the time capture-logs waits for its own Kafka write.
ATTEMPT_TIMEOUT_SECONDS = 30
RETRY_BASE_DELAY_MS = 100
RETRY_MAX_DELAY_MS = 5_000
DRAIN_POLL_SECONDS = 0.05

RECORDS_COUNTER = Counter(
    "logs_internal_producer_records",
    "Internal log records sent to capture-logs, by source and outcome. Only a sent record reaches the logs product.",
    labelnames=["source", "outcome"],
)
BUFFERED_BYTES_GAUGE = Gauge(
    "logs_internal_producer_buffered_bytes",
    "Bytes of internal log records a producer holds in memory, queued, waiting or in flight.",
)
IN_FLIGHT_GAUGE = Gauge("logs_internal_producer_in_flight_requests", "Requests a producer has open to capture-logs.")

GetTeamApiToken = Callable[[int], Awaitable[str | None]]


@frozen
class InternalLogsProducerConfig:
    url: str
    signing_keys: str = dataclasses.field(repr=False)
    teams: str
    max_in_flight: int
    max_buffered_bytes: int
    retry_timeout_ms: int

    @classmethod
    def from_settings(cls) -> "InternalLogsProducerConfig":
        return cls(
            url=settings.LOGS_INTERNAL_PRODUCER_URL,
            signing_keys=settings.LOGS_INTERNAL_INGESTION_SIGNING_KEYS,
            teams=settings.LOGS_INTERNAL_PRODUCER_TEAMS,
            max_in_flight=settings.LOGS_INTERNAL_PRODUCER_MAX_IN_FLIGHT,
            max_buffered_bytes=settings.LOGS_INTERNAL_PRODUCER_MAX_BUFFERED_BYTES,
            retry_timeout_ms=settings.LOGS_INTERNAL_PRODUCER_RETRY_TIMEOUT_MS,
        )


@frozen
class InternalLogEntry:
    team_id: int
    log_source_id: str
    instance_id: str
    timestamp: datetime
    level: str
    message: str


@frozen
class _Batch:
    source: str
    team_id: int
    records: list[bytes]


# Identity equality, so each request is its own key in the in-flight map.
@frozen(eq=False)
class _Request:
    source: str
    team_id: int
    records: list[bytes]
    byte_count: int


@frozen
class _AttemptResult:
    outcome: Literal["sent", "rejected", "unknown_team", "retry"]
    detail: str


def _count_records(source: str, outcome: str, records: int) -> None:
    if records > 0:
        RECORDS_COUNTER.labels(source=source, outcome=outcome).inc(records)


def _team_matcher(teams: str) -> Callable[[int], bool]:
    if teams.strip() == "*":
        return lambda _team_id: True
    allowed = {int(part) for part in (part.strip() for part in teams.split(",")) if part.isdigit()}
    return allowed.__contains__


class InternalLogsProducer:
    """Delivery runs in background tasks on the running event loop, so a slow or down capture-logs never slows
    the caller. A record is lost only when it is invalid, the buffer is full, its retries time out, capture-logs
    rejects it, or `drain` times out."""

    def __init__(self, config: InternalLogsProducerConfig, get_team_api_token: GetTeamApiToken) -> None:
        self._config = config
        self._get_team_api_token = get_team_api_token
        self._enabled = bool(config.url) and bool(config.signing_keys.strip())
        self._is_team_enabled = _team_matcher(config.teams)
        self._waiting: dict[tuple[str, int], _Batch] = {}
        self._buffered_bytes = 0
        self._in_flight: dict[_Request, asyncio.Task[None]] = {}
        self._stopped = False
        self._session: aiohttp.ClientSession | None = None

    def skip_looping(self, source: str, entries: Iterable[InternalLogEntry]) -> None:
        """Counts the records `enqueue` would send, as `loop_guard`, so logs kept out of a loop show on the dashboard."""
        if not self._enabled or source not in INTERNAL_SOURCE_SERVICE_NAMES:
            return
        _count_records(source, "loop_guard", sum(1 for entry in entries if self._is_team_enabled(entry.team_id)))

    def enqueue(self, source: str, entries: Iterable[InternalLogEntry]) -> None:
        if not self._enabled or source not in INTERNAL_SOURCE_SERVICE_NAMES:
            return
        invalid = dropped = abandoned = 0
        for entry in entries:
            if not self._is_team_enabled(entry.team_id):
                continue
            if self._stopped:
                abandoned += 1
                continue
            try:
                record = _encode_otlp_log_record(entry)
            except (ValueError, TypeError, OverflowError, AttributeError):
                invalid += 1
                continue
            if self._buffered_bytes + len(record) > self._config.max_buffered_bytes:
                dropped += 1
                continue
            self._buffered_bytes += len(record)
            key = (source, entry.team_id)
            batch = self._waiting.setdefault(key, _Batch(source=source, team_id=entry.team_id, records=[]))
            batch.records.append(record)
        _count_records(source, "invalid", invalid)
        _count_records(source, "dropped", dropped)
        _count_records(source, "abandoned", abandoned)
        self._report()

    def flush(self) -> None:
        """Starts sending the waiting records. Call it from inside a running event loop."""
        self._pump()

    async def drain(self, timeout_seconds: float) -> None:
        """Sends what is left until the timeout, then stops and counts the rest as abandoned. Call on shutdown."""
        deadline = time.monotonic() + timeout_seconds
        self._pump()
        while not self._stopped and not self._is_idle() and time.monotonic() < deadline:
            await asyncio.sleep(min(DRAIN_POLL_SECONDS, deadline - time.monotonic()))
        if not self._stopped and not self._is_idle():
            self._abandon()
            await asyncio.gather(*self._in_flight.values(), return_exceptions=True)
        self._stopped = True
        if self._session is not None:
            await self._session.close()
            self._session = None

    def _abandon(self) -> None:
        self._stopped = True
        unsent: list[_Batch | _Request] = [*self._waiting.values(), *self._in_flight]
        for item in unsent:
            _count_records(item.source, "abandoned", len(item.records))
        logger.warning(
            "Internal logs producer stopped before all records were sent",
            abandoned_records=sum(len(item.records) for item in unsent),
            in_flight_requests=len(self._in_flight),
        )
        self._waiting.clear()
        self._buffered_bytes = sum(request.byte_count for request in self._in_flight)
        for task in self._in_flight.values():
            task.cancel()
        self._report()

    def _pump(self) -> None:
        while not self._stopped and len(self._in_flight) < self._config.max_in_flight and self._waiting:
            key = next(iter(self._waiting))
            batch = self._waiting.pop(key)
            request = _take_request(batch)
            if batch.records:
                self._waiting[key] = batch
            task = asyncio.get_running_loop().create_task(self._deliver(request))
            # A callback, not a `finally`, because a task cancelled before it starts never runs its body.
            task.add_done_callback(functools.partial(self._release, request))
            self._in_flight[request] = task
        self._report()

    def _release(self, request: _Request, _task: "asyncio.Task[None]") -> None:
        self._in_flight.pop(request, None)
        self._buffered_bytes -= request.byte_count
        self._pump()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _has_stopped(self) -> bool:
        return self._stopped

    def _is_idle(self) -> bool:
        return not self._in_flight and not self._waiting

    def _report(self) -> None:
        BUFFERED_BYTES_GAUGE.set(self._buffered_bytes)
        IN_FLIGHT_GAUGE.set(len(self._in_flight))

    async def _deliver(self, request: _Request) -> None:
        body = _otlp_body(request.source, request.records)
        deadline = time.monotonic() + self._config.retry_timeout_ms / 1000
        attempt = 0
        while not self._stopped:
            result = await self._attempt(request.source, request.team_id, body, deadline)
            # A call, not the attribute, because mypy keeps the loop's narrowing across the await.
            if self._has_stopped():
                return
            if result.outcome != "retry":
                _count_records(request.source, result.outcome, len(request.records))
                if result.outcome == "rejected":
                    logger.warning(
                        "Internal logs batch rejected by capture-logs",
                        source=request.source,
                        team_id=request.team_id,
                        status=result.detail,
                    )
                return
            wait_seconds = random.random() * min(RETRY_MAX_DELAY_MS, RETRY_BASE_DELAY_MS * 2**attempt) / 1000
            if time.monotonic() + wait_seconds > deadline:
                _count_records(request.source, "failed", len(request.records))
                logger.warning(
                    "Internal logs batch failed after retries",
                    source=request.source,
                    team_id=request.team_id,
                    attempts=attempt + 1,
                    last=result.detail,
                )
                return
            await asyncio.sleep(wait_seconds)
            attempt += 1

    async def _attempt(self, source: str, team_id: int, body: bytes, deadline: float) -> _AttemptResult:
        try:
            # A team lookup has no timeout of its own, so a stalled database would hold this request slot past the deadline.
            api_token = await asyncio.wait_for(
                self._get_team_api_token(team_id), timeout=max(0.0, deadline - time.monotonic())
            )
            if self._stopped:
                return _AttemptResult(outcome="retry", detail="stopped")
            if not api_token:
                return _AttemptResult(outcome="unknown_team", detail=str(team_id))
            if self._session is None:
                # nosemgrep: aiohttp-missing-trust-env -- the in-cluster capture-logs service must bypass the egress proxy
                self._session = aiohttp.ClientSession()
            async with self._session.post(
                self._config.url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_token}",
                    INTERNAL_LOGS_HTTP_HEADER: sign_internal_logs(self._config.signing_keys, source, team_id),
                },
                timeout=aiohttp.ClientTimeout(
                    total=max(0.001, min(ATTEMPT_TIMEOUT_SECONDS, deadline - time.monotonic()))
                ),
                # A redirect turns the POST into a GET without a body, which can still answer 200.
                allow_redirects=False,
            ) as response:
                await response.read()
                status = response.status
            if 200 <= status < 300:
                return _AttemptResult(outcome="sent", detail=str(status))
            retriable = status >= 500 or status in (408, 429)
            return _AttemptResult(outcome="retry" if retriable else "rejected", detail=str(status))
        except Exception as error:
            # The type only, because the repr of a response error holds the signed request headers.
            return _AttemptResult(outcome="retry", detail=type(error).__name__)


def _encode_otlp_log_record(entry: InternalLogEntry) -> bytes:
    timestamp = entry.timestamp if entry.timestamp.tzinfo else entry.timestamp.replace(tzinfo=UTC)
    record: dict[str, Any] = {
        "timeUnixNano": str(int(timestamp.timestamp() * 1_000_000) * 1_000),
        "severityText": entry.level.upper(),
        "severityNumber": SEVERITY_NUMBERS.get(entry.level, 0),
        "body": {"stringValue": _valid_utf8(entry.message[:MAX_MESSAGE_LENGTH])},
        "attributes": [
            {"key": "log_source_id", "value": {"stringValue": entry.log_source_id}},
            {"key": "instance_id", "value": {"stringValue": entry.instance_id}},
        ],
    }
    # Not ensure_ascii, because an escaped code point above U+FFFF takes 12 bytes and breaks the MAX_MESSAGE_LENGTH bound.
    return json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode()


def _valid_utf8(text: str) -> str:
    # capture-logs rejects a whole request that holds one unpaired surrogate. This joins valid pairs and replaces the rest.
    return text.encode("utf-16", "surrogatepass").decode("utf-16", "replace")


def _take_request(batch: _Batch) -> _Request:
    """Removes up to MAX_REQUEST_RECORD_BYTES of records from the front of the batch, and at least one."""
    count = 0
    total = 0
    while count < len(batch.records):
        record_bytes = len(batch.records[count])
        if count > 0 and total + record_bytes > MAX_REQUEST_RECORD_BYTES:
            break
        total += record_bytes
        count += 1
    records = batch.records[:count]
    del batch.records[:count]
    return _Request(source=batch.source, team_id=batch.team_id, records=records, byte_count=total)


def _otlp_body(source: str, records: list[bytes]) -> bytes:
    resource = json.dumps(
        {"attributes": [{"key": "service.name", "value": {"stringValue": INTERNAL_SOURCE_SERVICE_NAMES[source]}}]}
    )
    scope = json.dumps({"name": source})
    return b"".join(
        [
            f'{{"resourceLogs":[{{"resource":{resource},"scopeLogs":[{{"scope":{scope},"logRecords":['.encode(),
            b",".join(records),
            b"]}]}]}",
        ]
    )
