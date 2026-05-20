import json
import asyncio
from collections.abc import AsyncGenerator
from typing import Optional

from django.conf import settings

import structlog
import redis.exceptions as redis_exceptions
from asgiref.sync import async_to_sync

from posthog.redis import get_async_client

logger = structlog.get_logger(__name__)

# Keep enough live history for users who open an in-progress run late while
# still bounding Redis growth for streams with a one-hour TTL.
TASK_RUN_STREAM_MAX_LENGTH = 20_000
TASK_RUN_STREAM_TIMEOUT = 60 * 60  # 60 minutes
TASK_RUN_STREAM_PREFIX = "task-run-stream:"
TASK_RUN_STREAM_READ_COUNT = 16
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


class TaskRunStreamError(Exception):
    pass


def get_task_run_stream_key(run_id: str) -> str:
    return f"{TASK_RUN_STREAM_PREFIX}{run_id}"


class TaskRunRedisStream:
    """Manages task run event streaming via Redis streams.

    Uses JSON serialization (not pickle) since sandbox ACP events are already JSON.
    """

    def __init__(
        self,
        stream_key: str,
        timeout: int = TASK_RUN_STREAM_TIMEOUT,
        max_length: int = TASK_RUN_STREAM_MAX_LENGTH,
    ):
        self._stream_key = stream_key
        self._redis_client = get_async_client(settings.REDIS_URL)
        self._timeout = timeout
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

    async def read_stream(
        self,
        start_id: str = "0",
        block_ms: int = 100,
        count: Optional[int] = TASK_RUN_STREAM_READ_COUNT,
        keepalive_interval_seconds: float | None = None,
    ) -> AsyncGenerator[dict, None]:
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
        block_ms: int = 100,
        count: Optional[int] = TASK_RUN_STREAM_READ_COUNT,
        keepalive_interval_seconds: float | None = None,
    ) -> AsyncGenerator[TaskRunStreamEntryOrKeepalive, None]:
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

    async def mark_complete(self) -> None:
        """Write a completion sentinel to signal end of stream."""
        await self.write_event({"type": "STREAM_STATUS", "status": "complete"})

    async def mark_error(self, error: str) -> None:
        """Write an error sentinel to signal stream failure."""
        await self.write_event({"type": "STREAM_STATUS", "status": "error", "error": error[:500]})

    async def delete_stream(self) -> bool:
        """Delete the Redis stream. Returns True if deleted."""
        try:
            return await self._redis_client.delete(self._stream_key) > 0
        except Exception:
            logger.exception("task_run_stream_delete_failed", stream_key=self._stream_key)
            return False


def publish_task_run_stream_event(run_id: str, event: dict) -> str | None:
    """Synchronously publish a task-run event to Redis.

    This is intended for sync Django model/view code that needs to mirror
    user-visible task-run events into the live SSE stream.
    """

    async def _publish() -> str:
        redis_stream = TaskRunRedisStream(get_task_run_stream_key(run_id))
        return await redis_stream.write_event(event)

    try:
        return async_to_sync(_publish)()
    except Exception:
        logger.exception("task_run_stream_publish_failed", run_id=run_id)
        return None
