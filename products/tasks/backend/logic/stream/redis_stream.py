import json
import asyncio
from collections.abc import AsyncGenerator
from typing import Optional

from django.conf import settings

import structlog
import redis.exceptions as redis_exceptions
from asgiref.sync import async_to_sync

from products.tasks.backend.logic.services.connection_token import SANDBOX_EVENT_INGEST_TOKEN_TTL
from products.tasks.backend.logic.services.sandbox_config import SANDBOX_TTL_SECONDS
from products.tasks.backend.redis import get_tasks_stream_redis_async

logger = structlog.get_logger(__name__)

# Keep enough live history for users who open an in-progress run late while
# still bounding Redis growth to the sandbox lifetime.
TASK_RUN_STREAM_MAX_LENGTH = 20_000
TASK_RUN_STREAM_TIMEOUT = SANDBOX_TTL_SECONDS
TASK_RUN_STREAM_SEQUENCE_TIMEOUT = int(SANDBOX_EVENT_INGEST_TOKEN_TTL.total_seconds())
TASK_RUN_STREAM_PREFIX = "task-run-stream:"
TASK_RUN_STREAM_READ_COUNT = 16
# XREAD BLOCK is push-based (XADD wakes the blocked client immediately), so a
# longer block only cuts idle polling — it never delays delivery. Keep it under
# the keepalive interval so idle readers still wake in time to emit one.
TASK_RUN_STREAM_READ_BLOCK_MS = 5_000
TASK_RUN_STREAM_WAIT_INITIAL_DELAY_SECONDS = 0.05
TASK_RUN_STREAM_WAIT_DELAY_INCREMENT_SECONDS = 0.15
TASK_RUN_STREAM_WAIT_MAX_DELAY_SECONDS = 2.0
TASK_RUN_STREAM_WAIT_TIMEOUT_SECONDS = 120.0  # sandbox provisioning can be slow

DATA_KEY = b"data"
TaskRunStreamEntry = tuple[str, dict]
TaskRunStreamEntryOrKeepalive = TaskRunStreamEntry | None


def _normalize_stream_id(stream_id: str | bytes) -> str:
    if isinstance(stream_id, bytes):
        return stream_id.decode("utf-8")
    return stream_id


def _normalize_redis_int(value: bytes | str | int | None) -> int:
    if value is None:
        return 0
    if isinstance(value, bytes):
        return int(value.decode("utf-8"))
    return int(value)


def _stream_id_sort_key(stream_id: str) -> tuple[int, int]:
    """Parse a Redis stream ID ('<ms>-<seq>') into a comparable (ms, seq) tuple."""
    ms_part, _, seq_part = stream_id.partition("-")
    try:
        return (int(ms_part), int(seq_part) if seq_part else 0)
    except ValueError:
        return (0, 0)


class TaskRunStreamError(Exception):
    pass


class TaskRunStreamSequenceGap(Exception):
    def __init__(self, *, expected_sequence: int, received_sequence: int, last_accepted_seq: int):
        self.expected_sequence = expected_sequence
        self.received_sequence = received_sequence
        self.last_accepted_seq = last_accepted_seq
        super().__init__(f"Expected sequence {expected_sequence}, got {received_sequence}")


class TaskRunStreamCompletionSequenceMismatch(Exception):
    def __init__(self, *, final_sequence: int, last_accepted_seq: int):
        self.final_sequence = final_sequence
        self.last_accepted_seq = last_accepted_seq
        super().__init__(
            f"Cannot complete stream at sequence {final_sequence}; last accepted sequence is {last_accepted_seq}"
        )


class TaskRunStreamAlreadyCompleted(Exception):
    def __init__(self, *, last_accepted_seq: int):
        self.last_accepted_seq = last_accepted_seq
        super().__init__("Task run stream is already complete")


def get_task_run_stream_key(run_id: str) -> str:
    return f"{TASK_RUN_STREAM_PREFIX}{run_id}"


def get_task_run_stream_sequence_key(stream_key: str) -> str:
    return f"{stream_key}:last-seq"


def get_task_run_stream_completed_key(stream_key: str) -> str:
    return f"{stream_key}:completed"


def get_task_run_stream_agent_active_key(stream_key: str) -> str:
    return f"{stream_key}:ingest-agent-active"


def get_task_run_stream_heartbeat_key(stream_key: str) -> str:
    return f"{stream_key}:ingest-heartbeat"


class TaskRunRedisStream:
    """Manages task run event streaming via Redis streams.

    Uses JSON serialization (not pickle) since sandbox ACP events are already JSON.
    """

    def __init__(
        self,
        stream_key: str,
        use_dedicated: bool = False,
        timeout: int = TASK_RUN_STREAM_TIMEOUT,
        max_length: int = TASK_RUN_STREAM_MAX_LENGTH,
    ):
        self._stream_key = stream_key
        self._redis_client = get_tasks_stream_redis_async(use_dedicated)
        self._timeout = timeout
        self._sequence_timeout = max(timeout, TASK_RUN_STREAM_SEQUENCE_TIMEOUT)
        self._max_length = max_length

    async def initialize(self) -> None:
        """Set expiry on the stream key to prevent unbounded growth."""
        await self._redis_client.expire(self._stream_key, self._timeout)

    async def exists(self) -> bool:
        """Return whether the Redis stream key already exists."""
        return bool(await self._redis_client.exists(self._stream_key))

    async def wait_for_stream(self) -> bool:
        """Wait for the stream to be created using linear backoff.

        Returns True if the stream exists, False on timeout.
        """
        delay = TASK_RUN_STREAM_WAIT_INITIAL_DELAY_SECONDS
        start_time = asyncio.get_running_loop().time()

        while True:
            elapsed = asyncio.get_running_loop().time() - start_time
            if elapsed >= TASK_RUN_STREAM_WAIT_TIMEOUT_SECONDS:
                logger.debug(
                    "task_run_stream_wait_timeout",
                    stream_key=self._stream_key,
                    elapsed=f"{elapsed:.2f}s",
                )
                return False

            if await self.exists():
                return True

            await asyncio.sleep(delay)
            delay = min(
                delay + TASK_RUN_STREAM_WAIT_DELAY_INCREMENT_SECONDS,
                TASK_RUN_STREAM_WAIT_MAX_DELAY_SECONDS,
            )

    async def get_latest_stream_id(self) -> str | None:
        """Return the latest stream ID if the stream has any events."""
        messages = await self._redis_client.xrevrange(self._stream_key, count=1)
        if not messages:
            return None
        stream_id, _message = messages[0]
        return _normalize_stream_id(stream_id)

    async def get_first_stream_id(self) -> str | None:
        """Return the oldest surviving stream ID, or None if the stream is empty."""
        messages = await self._redis_client.xrange(self._stream_key, count=1)
        if not messages:
            return None
        stream_id, _message = messages[0]
        return _normalize_stream_id(stream_id)

    async def get_length(self) -> int:
        """Return the current number of entries in the stream."""
        return _normalize_redis_int(await self._redis_client.xlen(self._stream_key))

    async def resume_point_trimmed(self, last_event_id: str) -> bool:
        """Return True if a reconnect from last_event_id has lost trimmed events.

        A client resumes via XREAD after its Last-Event-ID, which only returns
        entries strictly newer than that ID. If the requested ID is older than
        the oldest surviving entry, the events immediately after it were evicted
        by the maxlen trim and are gone for good — an undetectable gap otherwise.
        """
        if last_event_id in ("", "0"):
            return False
        first_id = await self.get_first_stream_id()
        if first_id is None:
            return False
        return _stream_id_sort_key(last_event_id) < _stream_id_sort_key(first_id)

    async def read_stream(
        self,
        start_id: str = "0",
        block_ms: int = TASK_RUN_STREAM_READ_BLOCK_MS,
        count: Optional[int] = TASK_RUN_STREAM_READ_COUNT,
        keepalive_interval_seconds: float | None = None,
    ) -> AsyncGenerator[dict]:
        async for item in self.read_stream_entries(
            start_id=start_id,
            block_ms=block_ms,
            count=count,
            keepalive_interval_seconds=keepalive_interval_seconds,
        ):
            if item is None:
                continue
            _stream_id, data = item
            yield data

    async def read_stream_entries(
        self,
        start_id: str = "0",
        block_ms: int = TASK_RUN_STREAM_READ_BLOCK_MS,
        count: Optional[int] = TASK_RUN_STREAM_READ_COUNT,
        keepalive_interval_seconds: float | None = None,
    ) -> AsyncGenerator[TaskRunStreamEntryOrKeepalive]:
        """Read events from the Redis stream.

        Yields Redis stream IDs and parsed JSON dicts.
        When keepalive_interval_seconds is set, yields None after that many
        idle seconds so callers can inject protocol-level keepalives.
        Stops when a complete sentinel is received.
        Raises TaskRunStreamError on error sentinel or timeout.
        """
        current_id = start_id
        start_time = asyncio.get_running_loop().time()
        last_yield_time = start_time

        while True:
            now = asyncio.get_running_loop().time()
            if now - start_time > self._timeout:
                raise TaskRunStreamError("Stream timeout — task run took too long")

            try:
                messages = await self._redis_client.xread(
                    {self._stream_key: current_id},
                    block=block_ms,
                    count=count,
                )

                if not messages:
                    now = asyncio.get_running_loop().time()
                    if keepalive_interval_seconds is not None and now - last_yield_time >= keepalive_interval_seconds:
                        last_yield_time = now
                        yield None
                    continue

                for _, stream_messages in messages:
                    for stream_id, message in stream_messages:
                        normalized_stream_id = _normalize_stream_id(stream_id)
                        current_id = normalized_stream_id
                        raw = message.get(DATA_KEY, b"")
                        data = json.loads(raw)

                        if data.get("type") == "STREAM_STATUS":
                            status: str = data.get("status", "")
                            if status == "complete":
                                return
                            elif status == "error":
                                raise TaskRunStreamError(data.get("error", "Unknown stream error"))
                        else:
                            last_yield_time = asyncio.get_running_loop().time()
                            yield normalized_stream_id, data

            except (TaskRunStreamError, GeneratorExit):
                raise
            except redis_exceptions.ConnectionError:
                raise TaskRunStreamError("Connection lost to task run stream")
            except redis_exceptions.TimeoutError:
                raise TaskRunStreamError("Stream read timeout")
            except redis_exceptions.RedisError:
                raise TaskRunStreamError("Stream read error")

    async def write_event(self, event: dict) -> str:
        """Write a single event to the stream.

        Refreshes TTL on every write (sliding window) so long-running tasks
        don't expire mid-stream. This is especially important for the sync
        publish path (publish_task_run_stream_event) which bypasses initialize().
        """
        raw = json.dumps(event)
        stream_id = await self._redis_client.xadd(
            self._stream_key,
            {DATA_KEY: raw},
            maxlen=self._max_length,
            approximate=True,
        )
        await self._redis_client.expire(self._stream_key, self._timeout)
        return _normalize_stream_id(stream_id)

    async def get_last_sequence(self) -> int:
        sequence_key = get_task_run_stream_sequence_key(self._stream_key)
        last_sequence_raw = await self._redis_client.get(sequence_key)
        if last_sequence_raw is not None:
            await self._redis_client.expire(sequence_key, self._sequence_timeout)
        return _normalize_redis_int(last_sequence_raw)

    async def set_agent_active(self, active: bool) -> None:
        await self._redis_client.set(
            get_task_run_stream_agent_active_key(self._stream_key),
            "1" if active else "0",
            ex=self._timeout,
        )

    async def get_agent_active(self) -> bool:
        active_raw = await self._redis_client.get(get_task_run_stream_agent_active_key(self._stream_key))
        return active_raw in (b"1", "1")

    async def claim_agent_active_heartbeat(self, throttle_seconds: int) -> bool:
        claimed = await self._redis_client.set(
            get_task_run_stream_heartbeat_key(self._stream_key),
            "1",
            ex=throttle_seconds,
            nx=True,
        )
        return bool(claimed)

    async def write_event_with_sequence(self, event: dict, sequence: int) -> str | None:
        """Write an event if it is the next unseen sequence number.

        Sequences must start at 1; sequence 0 is the initial sentinel and is
        treated as already accepted.
        Returns the Redis stream ID for newly accepted events, or None for a
        duplicate sequence that was already accepted on an earlier connection.
        """
        if settings.TEST:
            return await self._write_event_with_sequence_for_tests(event, sequence)

        sequence_key = get_task_run_stream_sequence_key(self._stream_key)
        completed_key = get_task_run_stream_completed_key(self._stream_key)
        raw = json.dumps(event)

        while True:
            async with self._redis_client.pipeline(transaction=True) as pipe:
                try:
                    await pipe.watch(sequence_key, completed_key)
                    last_sequence_raw = await pipe.get(sequence_key)
                    last_sequence = _normalize_redis_int(last_sequence_raw)
                    if await pipe.exists(completed_key):
                        raise TaskRunStreamAlreadyCompleted(last_accepted_seq=last_sequence)

                    if sequence <= last_sequence:
                        return None

                    if sequence != last_sequence + 1:
                        raise TaskRunStreamSequenceGap(
                            expected_sequence=last_sequence + 1,
                            received_sequence=sequence,
                            last_accepted_seq=last_sequence,
                        )

                    pipe.multi()
                    pipe.xadd(
                        self._stream_key,
                        {DATA_KEY: raw},
                        maxlen=self._max_length,
                        approximate=True,
                    )
                    pipe.expire(self._stream_key, self._timeout)
                    pipe.set(sequence_key, sequence, ex=self._sequence_timeout)
                    results = await pipe.execute()
                    return _normalize_stream_id(results[0])
                except redis_exceptions.WatchError:
                    continue

    async def _write_event_with_sequence_for_tests(self, event: dict, sequence: int) -> str | None:
        """Apply sequencing semantics without WATCH/MULTI for fakeredis."""
        sequence_key = get_task_run_stream_sequence_key(self._stream_key)
        completed_key = get_task_run_stream_completed_key(self._stream_key)
        last_sequence = await self.get_last_sequence()

        if await self._redis_client.exists(completed_key):
            raise TaskRunStreamAlreadyCompleted(last_accepted_seq=last_sequence)

        if sequence <= last_sequence:
            return None

        if sequence != last_sequence + 1:
            raise TaskRunStreamSequenceGap(
                expected_sequence=last_sequence + 1,
                received_sequence=sequence,
                last_accepted_seq=last_sequence,
            )

        stream_id = await self.write_event(event)
        await self._redis_client.set(sequence_key, sequence, ex=self._sequence_timeout)
        return stream_id

    async def mark_complete(self) -> None:
        """Write a completion sentinel to signal end of stream."""
        if settings.TEST:
            await self._mark_complete_for_tests()
            return

        completed_key = get_task_run_stream_completed_key(self._stream_key)
        raw = json.dumps({"type": "STREAM_STATUS", "status": "complete"})

        while True:
            async with self._redis_client.pipeline(transaction=True) as pipe:
                try:
                    await pipe.watch(completed_key)
                    if await pipe.exists(completed_key):
                        return

                    pipe.multi()
                    pipe.xadd(
                        self._stream_key,
                        {DATA_KEY: raw},
                        maxlen=self._max_length,
                        approximate=True,
                    )
                    pipe.expire(self._stream_key, self._timeout)
                    pipe.set(completed_key, "1", ex=self._sequence_timeout)
                    await pipe.execute()
                    return
                except redis_exceptions.WatchError:
                    continue

    async def _mark_complete_for_tests(self) -> None:
        completed_key = get_task_run_stream_completed_key(self._stream_key)
        if await self._redis_client.exists(completed_key):
            return

        await self.write_event({"type": "STREAM_STATUS", "status": "complete"})
        await self._redis_client.set(completed_key, "1", ex=self._sequence_timeout)

    async def mark_complete_after_sequence(self, final_sequence: int) -> None:
        """Write a completion sentinel only after the expected final sequence is accepted."""
        if settings.TEST:
            await self._mark_complete_after_sequence_for_tests(final_sequence)
            return

        sequence_key = get_task_run_stream_sequence_key(self._stream_key)
        completed_key = get_task_run_stream_completed_key(self._stream_key)
        raw = json.dumps({"type": "STREAM_STATUS", "status": "complete"})

        while True:
            async with self._redis_client.pipeline(transaction=True) as pipe:
                try:
                    await pipe.watch(sequence_key, completed_key)
                    last_sequence_raw = await pipe.get(sequence_key)
                    last_sequence = _normalize_redis_int(last_sequence_raw)
                    if await pipe.exists(completed_key):
                        return

                    if last_sequence != final_sequence:
                        raise TaskRunStreamCompletionSequenceMismatch(
                            final_sequence=final_sequence,
                            last_accepted_seq=last_sequence,
                        )

                    pipe.multi()
                    pipe.xadd(
                        self._stream_key,
                        {DATA_KEY: raw},
                        maxlen=self._max_length,
                        approximate=True,
                    )
                    pipe.expire(self._stream_key, self._timeout)
                    if last_sequence_raw is not None:
                        pipe.expire(sequence_key, self._sequence_timeout)
                    pipe.set(completed_key, "1", ex=self._sequence_timeout)
                    await pipe.execute()
                    return
                except redis_exceptions.WatchError:
                    continue

    async def _mark_complete_after_sequence_for_tests(self, final_sequence: int) -> None:
        sequence_key = get_task_run_stream_sequence_key(self._stream_key)
        completed_key = get_task_run_stream_completed_key(self._stream_key)
        last_sequence_raw = await self._redis_client.get(sequence_key)
        last_sequence = _normalize_redis_int(last_sequence_raw)

        if await self._redis_client.exists(completed_key):
            return

        if last_sequence != final_sequence:
            raise TaskRunStreamCompletionSequenceMismatch(
                final_sequence=final_sequence,
                last_accepted_seq=last_sequence,
            )

        await self.write_event({"type": "STREAM_STATUS", "status": "complete"})
        if last_sequence_raw is not None:
            await self._redis_client.expire(sequence_key, self._sequence_timeout)
        await self._redis_client.set(completed_key, "1", ex=self._sequence_timeout)

    async def mark_error(self, error: str) -> None:
        """Write an error sentinel to signal stream failure."""
        await self.write_event({"type": "STREAM_STATUS", "status": "error", "error": error[:500]})

    async def delete_stream(self) -> bool:
        """Delete the Redis stream. Returns True if deleted."""
        try:
            sequence_key = get_task_run_stream_sequence_key(self._stream_key)
            completed_key = get_task_run_stream_completed_key(self._stream_key)
            agent_active_key = get_task_run_stream_agent_active_key(self._stream_key)
            heartbeat_key = get_task_run_stream_heartbeat_key(self._stream_key)
            deleted = await self._redis_client.delete(
                self._stream_key, sequence_key, completed_key, agent_active_key, heartbeat_key
            )
            return _normalize_redis_int(deleted) > 0
        except Exception:
            logger.exception("task_run_stream_delete_failed", stream_key=self._stream_key)
            return False


def publish_task_run_stream_event(run_id: str, event: dict, use_dedicated: bool = False) -> str | None:
    """Synchronously publish a task-run event to Redis.

    This is intended for sync Django model/view code that needs to mirror
    user-visible task-run events into the live SSE stream.
    """

    async def _publish() -> str:
        redis_stream = TaskRunRedisStream(get_task_run_stream_key(run_id), use_dedicated)
        return await redis_stream.write_event(event)

    try:
        return async_to_sync(_publish)()
    except Exception:
        logger.exception("task_run_stream_publish_failed", run_id=run_id)
        return None


def publish_task_run_stream_complete(run_id: str, use_dedicated: bool = False) -> None:
    """Synchronously publish a completion sentinel for a task-run stream."""

    async def _publish() -> None:
        redis_stream = TaskRunRedisStream(get_task_run_stream_key(run_id), use_dedicated)
        await redis_stream.mark_complete()

    try:
        async_to_sync(_publish)()
    except Exception:
        logger.exception("task_run_stream_complete_publish_failed", run_id=run_id)
