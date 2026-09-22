import asyncio
import threading

import pytest
from unittest.mock import MagicMock, patch

from fakeredis.aioredis import FakeRedis

from products.managed_warehouse.backend import trino_execution as execution


@pytest.mark.asyncio
@pytest.mark.parametrize("occupied", ["organization", "global", "expired"])
async def test_admission_is_atomic_across_workers_and_reclaims_expired_leases(occupied: str) -> None:
    async with FakeRedis() as redis:
        now = (await redis.time())[0]
        global_key, org_key = "{trino-models}:global", "{trino-models}:org:example"
        key = org_key if occupied == "organization" else global_key
        limit = (
            execution.TRINO_ORGANIZATION_CONCURRENCY
            if occupied == "organization"
            else execution.TRINO_GLOBAL_CONCURRENCY
        )
        await redis.zadd(key, {str(i): now - 1 if occupied == "expired" else now + 1200 for i in range(limit)})
        admitted = await redis.eval(
            execution._ACQUIRE,
            2,
            global_key,
            org_key,
            "new",
            execution.TRINO_GLOBAL_CONCURRENCY,
            execution.TRINO_ORGANIZATION_CONCURRENCY,
            1200,
        )
        assert bool(admitted) == (occupied == "expired")
        expiry = await redis.zscore(org_key, "new")
        if occupied == "expired":
            assert expiry is not None and expiry >= now + 1200
            await redis.eval(execution._RELEASE, 2, global_key, org_key, "new")
            assert await redis.zcard(global_key) == await redis.zcard(org_key) == 0
        else:
            assert expiry is None


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_succeeds", [True, False])
async def test_cancellation_reaches_cursor_and_holds_lease_until_query_stops(cancel_succeeds: bool) -> None:
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    stopped = threading.Event()
    cursor = MagicMock()
    cursor.cancel.side_effect = stopped.set

    def execute(control: execution.TrinoQueryControl) -> int:
        control.attach(cursor)
        loop.call_soon_threadsafe(entered.set)
        assert stopped.wait(10)
        control.safe_to_release = cancel_succeeds
        return 1

    async with FakeRedis() as redis:
        with (
            patch.object(execution, "get_async_client", return_value=redis),
            patch.object(execution, "_slots", asyncio.Semaphore(1)),
        ):
            task = asyncio.create_task(execution.run_trino_model("example", execute))
            try:
                await asyncio.wait_for(entered.wait(), timeout=10)
                assert await redis.zcard("{trino-models}:global") == 1
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                cursor.cancel.assert_called()
                assert await redis.zcard("{trino-models}:global") == (0 if cancel_succeeds else 1)
            finally:
                stopped.set()
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_success_releases_capacity_and_preserves_result() -> None:
    async with FakeRedis() as redis:
        with (
            patch.object(execution, "get_async_client", return_value=redis),
            patch.object(execution, "_slots", asyncio.Semaphore(1)),
        ):
            assert await execution.run_trino_model("example", lambda control: 42) == 42
            assert await redis.zcard("{trino-models}:global") == 0
            assert await redis.zcard("{trino-models}:org:example") == 0
