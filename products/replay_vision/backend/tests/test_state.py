import asyncio
from typing import cast

import pytest

from redis import asyncio as aioredis

from products.replay_vision.backend.temporal.state import get_data_str_from_redis, store_data_in_redis


class TestStateCancellationResilience:
    @pytest.mark.asyncio
    async def test_cancelling_a_read_lets_the_redis_command_finish(self) -> None:
        # Replay Vision activities share one pooled aioredis client. If a cancelled read (e.g. an asyncio.gather
        # sibling failing) interrupts the command mid-flight, the connection returns to the pool dirty and the next
        # borrower desyncs the RESP stream ("unknown command '$3'"). The read must shield the command so it drains
        # cleanly before the cancellation propagates.
        started = asyncio.Event()
        command_finished = False

        async def slow_get(_key: str) -> None:
            nonlocal command_finished
            started.set()
            await asyncio.sleep(0.05)
            command_finished = True
            return None

        client = cast(aioredis.Redis, type("FakeRedis", (), {"get": staticmethod(slow_get)})())
        task = asyncio.create_task(get_data_str_from_redis(client, "some-key"))
        await started.wait()

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        await asyncio.sleep(0.1)
        assert command_finished, "the Redis command was cancelled mid-flight, poisoning the pooled connection"

    @pytest.mark.asyncio
    async def test_cancelling_a_write_lets_the_redis_command_finish(self) -> None:
        started = asyncio.Event()
        command_finished = False

        async def slow_setex(_key: str, _ttl: int, _value: bytes) -> None:
            nonlocal command_finished
            started.set()
            await asyncio.sleep(0.05)
            command_finished = True
            return None

        client = cast(aioredis.Redis, type("FakeRedis", (), {"setex": staticmethod(slow_setex)})())
        task = asyncio.create_task(store_data_in_redis(client, "some-key", "payload"))
        await started.wait()

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        await asyncio.sleep(0.1)
        assert command_finished, "the Redis command was cancelled mid-flight, poisoning the pooled connection"
