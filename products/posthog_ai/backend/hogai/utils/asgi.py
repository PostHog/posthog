from collections.abc import AsyncIterator, Callable, Iterable, Iterator
from typing import TypeVar

from asgiref.sync import sync_to_async

T = TypeVar("T")


class SyncIterableToAsync(AsyncIterator[T]):
    def __init__(self, iterable: Iterable[T]) -> None:
        self._iterable: Iterable[T] = iterable
        # async versions of the `next` and `iter` functions
        self.next_async: Callable = sync_to_async(self.next, thread_sensitive=False)
        self.iter_async: Callable = sync_to_async(iter, thread_sensitive=False)
        self.sync_iterator: Iterator[T] | None = None

    def __aiter__(self) -> AsyncIterator[T]:
        return self

    async def __anext__(self) -> T:
        if self.sync_iterator is None:
            self.sync_iterator = await self.iter_async(self._iterable)
        return await self.next_async(self.sync_iterator)

    @staticmethod
    def next(it: Iterator[T]) -> T:
        """
        asyncio expects `StopAsyncIteration` in place of `StopIteration`,
        so here's a modified in-built `next` function that can handle this.
        """
        try:
            return next(it)
        except StopIteration:
            raise StopAsyncIteration
