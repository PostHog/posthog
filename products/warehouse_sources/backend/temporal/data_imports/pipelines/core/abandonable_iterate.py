"""Pull items from a source in a way the caller can stop waiting for.

`async_iterate` runs each `next()` on a shared thread pool and waits for it. A source that blocks
in one call (a request with no deadline, a slow query, a long retry sleep) then holds the caller
and a pool thread for as long as the call takes. `AbandonableSourcePuller` gives each source its
own daemon thread, so the caller can stop waiting and the thread cannot keep the process alive.
"""

import queue
import asyncio
import threading
import contextvars
from collections.abc import AsyncIterable, AsyncIterator, Iterable, Iterator
from typing import Any, Generic, TypeVar, cast

from structlog import get_logger

T = TypeVar("T")

LOGGER = get_logger(__name__)

# (has_value, item). `has_value` is False when the source has no more items.
PulledItem = tuple[bool, T | None]


class SourceAbandonedError(BaseException):
    """Raised inside the code of a source that the pipeline no longer reads.

    It derives from `BaseException` so that the `except Exception` of a retry wrapper in the source
    does not catch it and continue the work.
    """


class _ThreadedSource(Generic[T]):
    """Runs a sync iterator on one daemon thread, one `next()` for each pull."""

    def __init__(self, iterator: Iterator[T]) -> None:
        self._iterator = iterator
        self._loop = asyncio.get_running_loop()
        self._requests: queue.SimpleQueue[asyncio.Future[PulledItem[T]] | None] = queue.SimpleQueue()
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None
        self._thread_stopped: asyncio.Future[None] = self._loop.create_future()

    def pull(self) -> "asyncio.Future[PulledItem[T]]":
        future: asyncio.Future[PulledItem[T]] = self._loop.create_future()
        if self._thread is None:
            # `threading.Thread` does not carry contextvars into the thread. The source needs them
            # for its log context and for the safe point hook. One copy serves every pull, so a
            # value the source sets in one pull is still set in the next one.
            context = contextvars.copy_context()
            self._thread = threading.Thread(
                target=context.run, args=(self._serve,), name="source-iter-abandonable", daemon=True
            )
            self._thread.start()
        self._requests.put(future)
        return future

    def stop(self) -> None:
        self._stopped.set()
        self._requests.put(None)

    async def wait_until_stopped(self) -> None:
        if self._thread is not None:
            await asyncio.shield(self._thread_stopped)

    def _serve(self) -> None:
        try:
            while True:
                future = self._requests.get()
                if future is None or self._stopped.is_set():
                    return
                try:
                    result: PulledItem[T] = (True, next(self._iterator))
                except StopIteration:
                    result = (False, None)
                except BaseException as error:
                    self._deliver(future, error=error)
                    return
                self._deliver(future, result=result)
        finally:
            self._close_iterator()
            try:
                self._loop.call_soon_threadsafe(self._mark_thread_stopped)
            except RuntimeError:
                pass

    def _mark_thread_stopped(self) -> None:
        if not self._thread_stopped.done():
            self._thread_stopped.set_result(None)

    def _deliver(
        self,
        future: "asyncio.Future[PulledItem[T]]",
        *,
        result: PulledItem[T] | None = None,
        error: BaseException | None = None,
    ) -> None:
        if self._stopped.is_set():
            return

        def resolve() -> None:
            if future.done():
                return
            if error is not None:
                future.set_exception(error)
            else:
                future.set_result(cast(PulledItem[T], result))

        try:
            self._loop.call_soon_threadsafe(resolve)
        except RuntimeError:
            # The event loop is closed, so nothing waits for this item.
            pass

    def _close_iterator(self) -> None:
        close = getattr(self._iterator, "close", None)
        if not callable(close):
            return
        try:
            close()
        except BaseException:
            LOGGER.debug("Closing the source iterator failed", exc_info=True)


class _AsyncSource(Generic[T]):
    """Runs an async iterator on the event loop, one task for each pull."""

    def __init__(self, iterator: AsyncIterator[T]) -> None:
        self._iterator = iterator
        self._pending: asyncio.Future[PulledItem[T]] | None = None

    def pull(self) -> "asyncio.Future[PulledItem[T]]":
        self._pending = asyncio.ensure_future(self._next())
        return self._pending

    async def _next(self) -> PulledItem[T]:
        try:
            return (True, await anext(self._iterator))
        except StopAsyncIteration:
            return (False, None)

    def stop(self) -> None:
        pending = self._pending
        if pending is None or pending.done():
            return
        pending.add_done_callback(_ignore_outcome)
        pending.cancel()


def _ignore_outcome(future: "asyncio.Future[Any]") -> None:
    if not future.cancelled():
        future.exception()


class AbandonableSourcePuller(Generic[T]):
    """Pulls the items of a sync or async source one at a time.

    The source advances only inside a pull, the same as with `async_iterate`. So while the caller
    works on an item, the source is idle and does not change any state it shares with the caller.
    """

    def __init__(self, iterable: Iterable[T] | AsyncIterable[T]) -> None:
        self._source: _ThreadedSource[T] | _AsyncSource[T]
        if isinstance(iterable, AsyncIterable):
            self._source = _AsyncSource(aiter(iterable))
        else:
            self._source = _ThreadedSource(iter(iterable))

    def pull(self) -> "asyncio.Future[PulledItem[T]]":
        """Ask for the next item. Call it again only after the future of the last call is done."""
        return self._source.pull()

    async def stop(self, *, abandon: bool = False) -> None:
        """Stop reading the source.

        A sync source normally finishes its current pull before returning, preserving the worker's
        bound on live source calls. Worker-shutdown preemption can instead abandon that pull. An
        async source gets a cancellation.
        """
        self._source.stop()
        if not abandon and isinstance(self._source, _ThreadedSource):
            await self._source.wait_until_stopped()
