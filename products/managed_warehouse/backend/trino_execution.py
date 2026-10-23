from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from time import monotonic
from typing import TYPE_CHECKING, TypeVar

import structlog

from posthog.sync import database_sync_to_async_pool

if TYPE_CHECKING:
    from collections.abc import Callable

    from trino.dbapi import Cursor

_Result = TypeVar("_Result")

TRINO_QUERY_SECONDS = 6 * 60 * 60
# Trino stops these queries for a cluster fault, not for the query itself, and asks the client to try
# again in a few minutes. The low-memory killer raises CLUSTER_OUT_OF_MEMORY when the whole cluster runs
# out of memory. TOO_MANY_REQUESTS_FAILED means a worker node crashed or stopped answering. A query over
# its own memory limit fails with another name.
TRANSIENT_TRINO_ERROR_NAMES = frozenset({"CLUSTER_OUT_OF_MEMORY", "TOO_MANY_REQUESTS_FAILED"})
TRANSIENT_TRINO_ERROR_RETRY_DELAYS_SECONDS = (2 * 60, 5 * 60)
_executor = ThreadPoolExecutor(thread_name_prefix="trino-model")

logger = structlog.get_logger(__name__)


class TrinoQueryControl:
    def __init__(
        self,
        query_seconds: float = TRINO_QUERY_SECONDS,
        on_processed_bytes: Callable[[int], None] | None = None,
    ) -> None:
        self.cancelled = threading.Event()
        self.finished = threading.Event()
        self.cursor: Cursor | None = None
        self.deadline = monotonic() + query_seconds
        self.on_processed_bytes = on_processed_bytes

    def checkpoint(self) -> None:
        if self.cancelled.is_set() or monotonic() >= self.deadline:
            raise TimeoutError("Trino model execution was canceled or exceeded its deadline")

    def attach(self, cursor: Cursor) -> None:
        self.cursor = cursor

    def record_processed_bytes(self, processed_bytes: object) -> None:
        if self.on_processed_bytes is not None and isinstance(processed_bytes, int):
            self.on_processed_bytes(processed_bytes)

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
    execute: Callable[[TrinoQueryControl], _Result],
    *,
    query_seconds: float = TRINO_QUERY_SECONDS,
    on_processed_bytes: Callable[[int], None] | None = None,
) -> _Result:
    control = TrinoQueryControl(query_seconds, on_processed_bytes)
    task = asyncio.create_task(database_sync_to_async_pool(execute, executor=_executor)(control))
    timeout = asyncio.timeout(query_seconds)
    try:
        async with timeout:
            return await asyncio.shield(task)
    except (asyncio.CancelledError, TimeoutError) as error:
        control.cancel()
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if isinstance(error, TimeoutError) and timeout.expired():
            raise TimeoutError(f"Trino model execution exceeded its {query_seconds / 60:g}-minute deadline") from error
        raise
    finally:
        control.finished.set()


def is_transient_trino_error(error: BaseException) -> bool:
    return getattr(error, "error_name", None) in TRANSIENT_TRINO_ERROR_NAMES


async def run_trino_model_with_retries(
    execute: Callable[[TrinoQueryControl], _Result],
    *,
    query_seconds: float = TRINO_QUERY_SECONDS,
    retry_delays: tuple[float, ...] = TRANSIENT_TRINO_ERROR_RETRY_DELAYS_SECONDS,
    on_processed_bytes: Callable[[int], None] | None = None,
) -> _Result:
    """Run ``execute`` again after a transient Trino cluster fault. All attempts share one deadline.

    ``on_processed_bytes`` receives the bytes each statement processed, in every attempt.
    """
    deadline = monotonic() + query_seconds
    for delay in retry_delays:
        try:
            return await run_trino_model(
                execute, query_seconds=deadline - monotonic(), on_processed_bytes=on_processed_bytes
            )
        except Exception as error:
            if not is_transient_trino_error(error) or monotonic() + delay >= deadline:
                raise
            logger.warning(
                "Trino cluster failed the query, retrying the model",
                error_name=getattr(error, "error_name", None),
                retry_in_seconds=delay,
            )
            await asyncio.sleep(delay)
    return await run_trino_model(execute, query_seconds=deadline - monotonic(), on_processed_bytes=on_processed_bytes)
