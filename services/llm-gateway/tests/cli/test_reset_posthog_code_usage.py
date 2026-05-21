from collections.abc import AsyncGenerator

import pytest
from fakeredis import aioredis as fakeredis

from llm_gateway.cli.reset_posthog_code_usage import reset_usage


@pytest.fixture
async def redis() -> AsyncGenerator[fakeredis.FakeRedis, None]:
    yield fakeredis.FakeRedis()


class TestResetUsage:
    async def test_resets_every_user_regardless_of_plan(self, redis: fakeredis.FakeRedis) -> None:
        # Free, pro, and unknown-plan users — all should be reset.
        keys = [
            "ratelimit:cost:user:user_cost_burst:posthog_code:100",
            "ratelimit:cost:user:user_cost_sustained:posthog_code:100:period:0",
            "ratelimit:cost:user:user_cost_burst:posthog_code:200",
            "ratelimit:cost:user:user_cost_sustained:posthog_code:200:period:0",
            "ratelimit:cost:user:user_cost_burst:posthog_code:300:tm2",
            "ratelimit:cost:user:user_cost_sustained:posthog_code:300:tm2:period:1",
        ]
        for k in keys:
            await redis.set(k, "10.0")

        deleted = await reset_usage(redis, dry_run=False)

        assert deleted == len(keys)
        for k in keys:
            assert await redis.get(k) is None

    async def test_dry_run_counts_without_deleting(self, redis: fakeredis.FakeRedis) -> None:
        await redis.set("ratelimit:cost:user:user_cost_burst:posthog_code:100", "1.0")
        await redis.set("ratelimit:cost:user:user_cost_sustained:posthog_code:100:period:0", "1.0")

        deleted = await reset_usage(redis, dry_run=True)

        assert deleted == 2
        assert await redis.get("ratelimit:cost:user:user_cost_burst:posthog_code:100") is not None
        assert await redis.get("ratelimit:cost:user:user_cost_sustained:posthog_code:100:period:0") is not None

    async def test_returns_zero_when_no_keys(self, redis: fakeredis.FakeRedis) -> None:
        assert await reset_usage(redis, dry_run=False) == 0

    async def test_leaves_unrelated_keys_untouched(self, redis: fakeredis.FakeRedis) -> None:
        # Other products, plan cache, and unrelated rate-limit scopes must survive.
        survivors = [
            "ratelimit:cost:user:user_cost_burst:other_product:100",
            "ratelimit:cost:user:user_cost_sustained:other_product:100:period:0",
            "plan:posthog_code:100",
            "ratelimit:burst:user:100",
            "some:other:key",
        ]
        for k in survivors:
            await redis.set(k, "x")
        await redis.set("ratelimit:cost:user:user_cost_burst:posthog_code:100", "1.0")

        deleted = await reset_usage(redis, dry_run=False)

        assert deleted == 1
        for k in survivors:
            assert await redis.get(k) is not None
