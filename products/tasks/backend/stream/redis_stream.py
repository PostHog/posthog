import json
import asyncio
from collections.abc import AsyncGenerator
from typing import Optional

from django.conf import settings

import structlog
import redis.exceptions as redis_exceptions

from posthog.redis import get_async_client

logger = structlog.get_logger(__name__)

TASK_RUN_STREAM_MAX_LENGTH = 2000
TASK_RUN_STREAM_TIMEOUT = 60 * 60  # 60 minutes
TASK_RUN_STREAM_PREFIX = "task-run-stream:"
TASK_RUN_STREAM_READ_COUNT = 16

DATA_KEY = b"data"


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

    async def wait_for_stream(self) -> bool:
        """Wait for the stream to be created using linear backoff.

        Returns True if the stream exists, False on timeout.
        """
        delay = 0.05
        delay_increment = 0.15
        max_delay = 2.0
        timeout = 120.0  # 2 min — sandbox provisioning can be slow
        start_time = asyncio.get_running_loop().time()

        while True:
            elapsed = asyncio.get_running_loop().time() - start_time
            if elapsed >= timeout:
                logger.debug(
                    "task_run_stream_wait_timeout",
                    stream_key=self._stream_key,
                    elapsed=f"{elapsed:.2f}s",
                )
                return False

            if await self._redis_client.exists(self._stream_key):
                return True

            await asyncio.sleep(delay)
            delay = min(delay + delay_increment, max_delay)

    async def read_stream(
        self,
        start_id: str = "0",
        block_ms: int = 100,
        count: Optional[int] = TASK_RUN_STREAM_READ_COUNT,
    ) -> AsyncGenerator[dict, None]:
        """Read events from the Redis stream.

        Yields parsed JSON dicts. Stops when a complete sentinel is received.
        Raises TaskRunStreamError on error sentinel or timeout.
        """
        current_id = start_id
        start_time = asyncio.get_running_loop().time()

        while True:
            if asyncio.get_running_loop().time() - start_time > self._timeout:
                raise TaskRunStreamError("Stream timeout — task run took too long")

            try:
                messages = await self._redis_client.xread(
                    {self._stream_key: current_id},
                    block=block_ms,
                    count=count,
                )

                if not messages:
                    continue

                for _, stream_messages in messages:
                    for stream_id, message in stream_messages:
                        current_id = stream_id
                        raw = message.get(DATA_KEY, b"")
                        data = json.loads(raw)

                        if data.get("type") == "STREAM_STATUS":
                            status: str = data.get("status", "")
                            if status == "complete":
                                return
                            elif status == "error":
                                raise TaskRunStreamError(data.get("error", "Unknown stream error"))
                        else:
                            yield data

            except (TaskRunStreamError, GeneratorExit):
                raise
            except redis_exceptions.ConnectionError:
                raise TaskRunStreamError("Connection lost to task run stream")
            except redis_exceptions.TimeoutError:
                raise TaskRunStreamError("Stream read timeout")
            except redis_exceptions.RedisError:
                raise TaskRunStreamError("Stream read error")

    async def write_event(self, event: dict) -> None:
        """Write a single event to the stream."""
        raw = json.dumps(event)
        await self._redis_client.xadd(
            self._stream_key,
            {DATA_KEY: raw},
            maxlen=self._max_length,
            approximate=True,
        )

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
