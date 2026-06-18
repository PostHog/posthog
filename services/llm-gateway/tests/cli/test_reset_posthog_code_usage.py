import argparse
from collections.abc import AsyncGenerator

import pytest
from fakeredis import aioredis as fakeredis

from llm_gateway.cli.reset_posthog_code_usage import _non_empty_user_id, reset_usage


@pytest.fixture
async def redis() -> AsyncGenerator[fakeredis.FakeRedis]:
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

    @pytest.mark.parametrize("user_id", [None, "100"])
    async def test_dry_run_counts_without_deleting(self, redis: fakeredis.FakeRedis, user_id: str | None) -> None:
        await redis.set("ratelimit:cost:user:user_cost_burst:posthog_code:100", "1.0")
        await redis.set("ratelimit:cost:user:user_cost_sustained:posthog_code:100:period:0", "1.0")

        deleted = await reset_usage(redis, dry_run=True, user_id=user_id)

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

    async def test_user_id_resets_only_that_user(self, redis: fakeredis.FakeRedis) -> None:
        target_keys = [
            "ratelimit:cost:user:user_cost_burst:posthog_code:100",
            "ratelimit:cost:user:user_cost_sustained:posthog_code:100:period:0",
            "ratelimit:cost:user:user_cost_burst:posthog_code:100:tm2",
            "ratelimit:cost:user:user_cost_sustained:posthog_code:100:tm2:period:1",
        ]
        # Other users, including one whose id is a prefix of the target's id (1 vs 100)
        # and one whose id starts with the target's id (1000 vs 100).
        other_keys = [
            "ratelimit:cost:user:user_cost_burst:posthog_code:1",
            "ratelimit:cost:user:user_cost_sustained:posthog_code:1:period:0",
            "ratelimit:cost:user:user_cost_burst:posthog_code:1000",
            "ratelimit:cost:user:user_cost_sustained:posthog_code:1000:period:0",
            "ratelimit:cost:user:user_cost_burst:posthog_code:200",
        ]
        for k in target_keys + other_keys:
            await redis.set(k, "1.0")

        deleted = await reset_usage(redis, dry_run=False, user_id="100")

        assert deleted == len(target_keys)
        for k in target_keys:
            assert await redis.get(k) is None
        for k in other_keys:
            assert await redis.get(k) is not None

    async def test_user_id_glob_metachars_do_not_expand_match(self, redis: fakeredis.FakeRedis) -> None:
        # A user_id like "10*" must be treated as a literal id, not a glob that
        # would match every user starting with "10".
        survivors = [
            "ratelimit:cost:user:user_cost_burst:posthog_code:100",
            "ratelimit:cost:user:user_cost_burst:posthog_code:1000",
            "ratelimit:cost:user:user_cost_burst:posthog_code:10abc",
            "ratelimit:cost:user:user_cost_sustained:posthog_code:100:period:0",
        ]
        for k in survivors:
            await redis.set(k, "1.0")

        deleted = await reset_usage(redis, dry_run=False, user_id="10*")

        assert deleted == 0
        for k in survivors:
            assert await redis.get(k) is not None

    def test_non_empty_user_id_rejects_empty_string(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError):
            _non_empty_user_id("")
