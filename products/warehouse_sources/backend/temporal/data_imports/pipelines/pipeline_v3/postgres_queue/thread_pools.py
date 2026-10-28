"""Thread pools for the load consumer process.

One group holds one thread for the full load. The load code calls `async_to_sync` from that
thread, and asgiref runs the coroutine on the consumer's event loop. Each `asyncio.to_thread` or
`sync_to_async(thread_sensitive=False)` call in that coroutine then submits a nested job to the
loop's default executor, and the group thread waits for it.

If the groups and their nested jobs share one pool, the pool deadlocks when the groups hold every
thread: each group waits for a nested job that has no thread to run on. The groups therefore get a
dedicated pool, and the default executor serves only the nested jobs. Both sizes come from the
consumer's concurrency, because the default size of `min(32, os.cpu_count() + 4)` changes with the
node type.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

from posthog.dataclasses import frozen

# The number of nested jobs that one group can have on the default executor at the same time.
# A nested job can itself call `async_to_sync` and wait for a job of its own, so the default
# executor must have more than one thread for each group.
NESTED_JOBS_PER_GROUP = 4
# Threads for the default-executor work that does not belong to a group, such as the log producer.
NESTED_POOL_HEADROOM = 8

GROUP_THREAD_NAME_PREFIX = "warehouse-load-group"
NESTED_THREAD_NAME_PREFIX = "warehouse-load-nested"


class LoaderThreadPoolTooSmallError(ValueError):
    pass


@frozen
class LoaderThreadPoolSizes:
    max_concurrency: int
    group_threads: int
    nested_threads: int

    @staticmethod
    def required_nested_threads(max_concurrency: int) -> int:
        return max_concurrency * NESTED_JOBS_PER_GROUP + NESTED_POOL_HEADROOM

    @classmethod
    def for_concurrency(cls, max_concurrency: int, nested_threads: int | None = None) -> LoaderThreadPoolSizes:
        """Size both pools for `max_concurrency` groups. Raise if `nested_threads` is below the need."""
        if max_concurrency < 1:
            raise ValueError(f"max_concurrency must be at least 1, got {max_concurrency}")
        required = cls.required_nested_threads(max_concurrency)
        if nested_threads is None:
            nested_threads = required
        if nested_threads < required:
            raise LoaderThreadPoolTooSmallError(
                f"The nested thread pool has {nested_threads} threads, but max_concurrency={max_concurrency} "
                f"needs at least {required} ({NESTED_JOBS_PER_GROUP} for each group plus {NESTED_POOL_HEADROOM}). "
                "Increase the pool or decrease max_concurrency."
            )
        return cls(max_concurrency=max_concurrency, group_threads=max_concurrency, nested_threads=nested_threads)


class LoaderThreadPools:
    def __init__(self, sizes: LoaderThreadPoolSizes) -> None:
        self.sizes = sizes
        self.group_executor = ThreadPoolExecutor(
            max_workers=sizes.group_threads, thread_name_prefix=GROUP_THREAD_NAME_PREFIX
        )
        self.nested_executor = ThreadPoolExecutor(
            max_workers=sizes.nested_threads, thread_name_prefix=NESTED_THREAD_NAME_PREFIX
        )

    def install(self, loop: asyncio.AbstractEventLoop) -> None:
        """Make the nested pool the default executor of `loop`."""
        loop.set_default_executor(self.nested_executor)

    def shutdown(self) -> None:
        self.group_executor.shutdown(wait=False, cancel_futures=True)
        self.nested_executor.shutdown(wait=False, cancel_futures=True)
