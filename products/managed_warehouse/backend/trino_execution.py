from __future__ import annotations

import random
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from time import monotonic
from typing import TYPE_CHECKING, TypeVar
from uuid import uuid4

import structlog
from redis.exceptions import RedisError

from posthog.redis import get_async_client
from posthog.sync import database_sync_to_async_pool

from products.managed_warehouse.backend.facade.contracts import TrinoCapacityUnavailable

if TYPE_CHECKING:
    from collections.abc import Callable

    from trino.dbapi import Cursor

_Result = TypeVar("_Result")

TRINO_QUERY_SECONDS = 15 * 60
# Cover admission, the client deadline, and the server lifetime of the last submitted statement.
TRINO_LEASE_SECONDS = 40 * 60
TRINO_GLOBAL_CONCURRENCY = 16
TRINO_ORGANIZATION_CONCURRENCY = 2
TRINO_WORKER_CONCURRENCY = 4
_executor = ThreadPoolExecutor(max_workers=TRINO_WORKER_CONCURRENCY, thread_name_prefix="trino-model")
_slots = asyncio.Semaphore(TRINO_WORKER_CONCURRENCY)
logger = structlog.get_logger(__name__)

_ACQUIRE = """
local now = tonumber(redis.call('TIME')[1])
for _, key in ipairs(KEYS) do redis.call('ZREMRANGEBYSCORE', key, '-inf', now) end
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[2]) or redis.call('ZCARD', KEYS[2]) >= tonumber(ARGV[3]) then return 0 end
for _, key in ipairs(KEYS) do
    redis.call('ZADD', key, now + tonumber(ARGV[4]), ARGV[1])
    redis.call('EXPIRE', key, ARGV[4])
end
return 1
"""
_RELEASE = """
for _, key in ipairs(KEYS) do redis.call('ZREM', key, ARGV[1]) end
return 1
"""


class TrinoQueryControl:
    def __init__(self, query_seconds: float = TRINO_QUERY_SECONDS) -> None:
        self.cancelled = threading.Event()
        self.finished = threading.Event()
        self.cursor: Cursor | None = None
        self.safe_to_release = True
        self.deadline = monotonic() + query_seconds

    def checkpoint(self) -> None:
        if self.cancelled.is_set() or monotonic() >= self.deadline:
            raise TimeoutError("Trino model execution was canceled or exceeded its deadline")

    def attach(self, cursor: Cursor) -> None:
        self.cursor = cursor
        self.safe_to_release = False

    def _cancel_until_finished(self) -> None:
        # execute() can still be waiting for its first nextUri when cancellation arrives.
        while not self.finished.is_set():
            if self.cursor is not None:
                try:
                    self.cursor.cancel()
                except Exception:
                    pass
            self.finished.wait(0.5)

    def cancel(self) -> None:
        if not self.cancelled.is_set():
            self.cancelled.set()
            threading.Thread(target=self._cancel_until_finished, name="trino-model-cancel", daemon=True).start()


async def run_trino_model(
    organization_id: str, execute: Callable[[TrinoQueryControl], _Result], *, query_seconds: float = TRINO_QUERY_SECONDS
) -> _Result:
    redis = get_async_client()
    keys = ["{trino-models}:global", f"{{trino-models}}:org:{organization_id}"]
    token = str(uuid4())
    acquired = False
    local_slot = False
    control = TrinoQueryControl(query_seconds)
    try:
        try:
            async with asyncio.timeout(120):
                while not acquired:
                    acquired = bool(
                        await redis.eval(
                            _ACQUIRE,
                            2,
                            *keys,
                            token,
                            TRINO_GLOBAL_CONCURRENCY,
                            TRINO_ORGANIZATION_CONCURRENCY,
                            TRINO_LEASE_SECONDS,
                        )
                    )
                    if not acquired:
                        await asyncio.sleep(random.uniform(1, 3))
                await _slots.acquire()
                local_slot = True
        except (TimeoutError, RedisError) as error:
            raise TrinoCapacityUnavailable("Trino model capacity is busy; retry admission") from error

        control = TrinoQueryControl(query_seconds)
        task = asyncio.create_task(database_sync_to_async_pool(execute, executor=_executor)(control))
        try:
            async with asyncio.timeout(query_seconds):
                return await asyncio.shield(task)
        except (asyncio.CancelledError, TimeoutError):
            control.cancel()
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            raise
        finally:
            control.finished.set()
    finally:
        try:
            # A lost cancellation response can leave a server query alive. Keep its lease until the server deadline passes.
            if acquired and control.safe_to_release:
                try:
                    await redis.eval(_RELEASE, 2, *keys, token)
                except Exception:
                    logger.warning("trino_model_lease_release_failed", organization_id=organization_id, exc_info=True)
        finally:
            if local_slot:
                _slots.release()
