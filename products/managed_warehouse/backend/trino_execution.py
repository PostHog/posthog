from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from time import monotonic
from typing import TYPE_CHECKING, TypeVar

from posthog.sync import database_sync_to_async_pool

if TYPE_CHECKING:
    from collections.abc import Callable

    from trino.dbapi import Cursor

_Result = TypeVar("_Result")

TRINO_QUERY_SECONDS = 6 * 60 * 60
_executor = ThreadPoolExecutor(thread_name_prefix="trino-model")


class TrinoQueryControl:
    def __init__(self, query_seconds: float = TRINO_QUERY_SECONDS) -> None:
        self.cancelled = threading.Event()
        self.finished = threading.Event()
        self.cursor: Cursor | None = None
        self.deadline = monotonic() + query_seconds

    def checkpoint(self) -> None:
        if self.cancelled.is_set() or monotonic() >= self.deadline:
            raise TimeoutError("Trino model execution was canceled or exceeded its deadline")

    def attach(self, cursor: Cursor) -> None:
        self.cursor = cursor

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
    execute: Callable[[TrinoQueryControl], _Result], *, query_seconds: float = TRINO_QUERY_SECONDS
) -> _Result:
    control = TrinoQueryControl(query_seconds)
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
