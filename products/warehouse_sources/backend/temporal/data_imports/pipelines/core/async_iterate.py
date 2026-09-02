import asyncio
import threading
import contextvars
from collections.abc import AsyncIterable, AsyncIterator, Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar, cast

T = TypeVar("T")

# Dedicated thread pool for source iteration so that long-running HTTP calls
# (e.g. Stripe API pagination) can't starve the default executor which is
# shared by logging, DB operations, and S3 writes.
_SOURCE_ITERATOR_EXECUTOR = ThreadPoolExecutor(max_workers=32, thread_name_prefix="source-iter")


async def async_iterate(iterable: Iterable[T] | AsyncIterable[T]) -> AsyncIterator[T]:
    """
    Normalize a sync or async iterable into an async iterator.

    Async iterables are yielded directly. Sync iterables are wrapped so that
    each call to `next()` runs in a dedicated thread pool, preventing
    blocking source HTTP calls from exhausting the default executor.
    """
    if isinstance(iterable, AsyncIterable):
        async for item in iterable:
            yield cast(T, item)
        return

    iterator = iter(iterable)
    lock = threading.Lock()
    loop = asyncio.get_running_loop()
    # loop.run_in_executor does not propagate contextvars across the thread
    # boundary (unlike asyncio.to_thread). Snapshot them once so logs emitted
    # from inside the source generator keep team_id / workflow_* and reach the
    # log_entries table via LogMessagesRenderer's produce path.
    ctx = contextvars.copy_context()

    def _next() -> tuple[bool, T | None]:
        with lock:
            try:
                return (True, next(iterator))
            except StopIteration:
                return (False, None)

    def _close() -> None:
        with lock:
            if hasattr(iterator, "close") and callable(iterator.close):
                iterator.close()

    try:
        while True:
            has_value, item = await loop.run_in_executor(_SOURCE_ITERATOR_EXECUTOR, ctx.run, _next)  # type: ignore
            if not has_value:
                break

            assert item is not None
            yield item
    finally:
        # Use a fresh context snapshot for cleanup. Reusing `ctx` would fail
        # with RuntimeError if the activity is cancelled mid-_next: the
        # in-flight _next may still be inside `ctx` on an executor thread,
        # and Context.run raises when re-entered. A failed _close would skip
        # iterator.close() and leave DB cursors / connections / tunnels held
        # open until garbage collection.
        cleanup_ctx = contextvars.copy_context()
        await loop.run_in_executor(_SOURCE_ITERATOR_EXECUTOR, cleanup_ctx.run, _close)
