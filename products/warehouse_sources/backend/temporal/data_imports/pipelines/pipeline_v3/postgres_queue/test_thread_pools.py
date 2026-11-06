import asyncio
import threading
from typing import Any

import pytest
from unittest.mock import patch

from asgiref.sync import async_to_sync
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.load import (
    process_batch,
    process_batches,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.thread_pools import (
    GROUP_THREAD_NAME_PREFIX,
    NESTED_THREAD_NAME_PREFIX,
    LoaderThreadPools,
    LoaderThreadPoolSizes,
    LoaderThreadPoolTooSmallError,
)
from products.warehouse_sources_queue.backend.core.jobs_db import PendingBatch

_LOAD_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.load"
_TIMEOUT_SECONDS = 10.0


def _make_batch(batch_index: int) -> PendingBatch:
    return PendingBatch(
        id=f"00000000-0000-0000-0000-{batch_index:012d}",
        team_id=1,
        schema_id=f"schema-{batch_index}",
        source_id="source-1",
        job_id="job-1",
        run_uuid="run-1",
        batch_index=batch_index,
        s3_path="s3://bucket/path",
        row_count=100,
        byte_size=1024,
        is_final_batch=False,
        total_batches=None,
        total_rows=None,
        sync_type="full_refresh",
        cumulative_row_count=0,
        resource_name="test_resource",
        is_resume=False,
        is_first_ever_sync=False,
        metadata={},
        latest_attempt=0,
    )


class TestLoaderThreadPools:
    @parameterized.expand(
        [
            ("single", "process_message", 2),
            ("single_many_groups", "process_message", 16),
            ("coalesced_set", "process_messages", 2),
        ]
    )
    def test_full_concurrency_finishes_when_the_nested_pool_is_no_larger_than_the_group_count(
        self, _name: str, patched: str, groups: int
    ):
        # The nested pool has one thread for each group, the smallest size at which a shared pool
        # deadlocks: every group holds a thread before any group submits its nested job.
        all_groups_hold_a_thread = threading.Barrier(groups)
        threads: list[tuple[str, str]] = []

        async def nested() -> str:
            return await asyncio.to_thread(lambda: threading.current_thread().name)

        def load(*args: Any, **kwargs: Any) -> None:
            all_groups_hold_a_thread.wait(timeout=_TIMEOUT_SECONDS)
            threads.append((threading.current_thread().name, async_to_sync(nested)()))

        async def run() -> None:
            pools = LoaderThreadPools(
                LoaderThreadPoolSizes(max_concurrency=groups, group_threads=groups, nested_threads=groups)
            )
            pools.install(asyncio.get_running_loop())
            try:
                if patched == "process_message":
                    loads = [process_batch(_make_batch(i), executor=pools.group_executor) for i in range(groups)]
                else:
                    loads = [process_batches([_make_batch(i)], executor=pools.group_executor) for i in range(groups)]
                await asyncio.wait_for(asyncio.gather(*loads), timeout=_TIMEOUT_SECONDS)
            finally:
                # Cancelling the queued jobs releases the group threads if the pools deadlock, so a
                # failure ends the test instead of hanging the process at interpreter exit.
                all_groups_hold_a_thread.abort()
                pools.shutdown()

        with patch(f"{_LOAD_MODULE}.{patched}", side_effect=load):
            asyncio.run(run())

        assert len(threads) == groups
        assert all(group.startswith(GROUP_THREAD_NAME_PREFIX) for group, _ in threads)
        assert all(nested_thread.startswith(NESTED_THREAD_NAME_PREFIX) for _, nested_thread in threads)


class TestLoaderThreadPoolSizes:
    @parameterized.expand(
        [
            ("default_at_8", 8, None, 40),
            ("default_at_16", 16, None, 72),
            ("override_at_the_minimum", 16, 72, 72),
            ("override_above_the_minimum", 16, 200, 200),
        ]
    )
    def test_sizes_follow_max_concurrency(
        self, _name: str, max_concurrency: int, override: int | None, expected_nested: int
    ):
        sizes = LoaderThreadPoolSizes.for_concurrency(max_concurrency, override)

        assert sizes.group_threads == max_concurrency
        assert sizes.nested_threads == expected_nested

    @parameterized.expand(
        [
            ("one_below_the_minimum", 16, 71),
            ("cpu_based_default_on_a_small_node", 16, 12),
            ("zero", 1, 0),
        ]
    )
    def test_a_nested_pool_below_the_need_is_rejected(self, _name: str, max_concurrency: int, override: int):
        with pytest.raises(LoaderThreadPoolTooSmallError, match=f"max_concurrency={max_concurrency}"):
            LoaderThreadPoolSizes.for_concurrency(max_concurrency, override)

    @parameterized.expand([(0,), (-1,)])
    def test_non_positive_concurrency_is_rejected(self, max_concurrency: int):
        with pytest.raises(ValueError, match="max_concurrency must be at least 1"):
            LoaderThreadPoolSizes.for_concurrency(max_concurrency)
