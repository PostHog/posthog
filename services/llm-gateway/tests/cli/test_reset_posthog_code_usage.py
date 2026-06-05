import argparse
from collections.abc import AsyncGenerator

import pytest
from fakeredis import aioredis as fakeredis

from llm_gateway.cli.reset_posthog_code_usage import (
    _non_empty_user_id,
    cost_patterns,
    product_patterns,
    request_patterns,
    reset_keys,
)

COST_BURST = "ratelimit:cost:user:user_cost_burst:posthog_code"
COST_SUSTAINED = "ratelimit:cost:user:user_cost_sustained:posthog_code"
PRODUCT = "ratelimit:cost:product:posthog_code"
REQ_BURST = "ratelimit:burst"
REQ_SUSTAINED = "ratelimit:sustained"


@pytest.fixture
async def redis() -> AsyncGenerator[fakeredis.FakeRedis, None]:
    yield fakeredis.FakeRedis()


async def _seed(redis: fakeredis.FakeRedis, *keys: str) -> None:
    for k in keys:
        await redis.set(k, "1.0")


async def _exists(redis: fakeredis.FakeRedis, key: str) -> bool:
    return await redis.get(key) is not None


class TestResetKeys:
    async def test_cost_patterns_reset_every_user(self, redis: fakeredis.FakeRedis) -> None:
        keys = [
            f"{COST_BURST}:100",
            f"{COST_SUSTAINED}:100:period:0",
            f"{COST_BURST}:300:tm2",
            f"{COST_SUSTAINED}:300:tm2:period:1",
        ]
        await _seed(redis, *keys)

        deleted = await reset_keys(redis, cost_patterns(None), dry_run=False)

        assert deleted == len(keys)
        for k in keys:
            assert not await _exists(redis, k)

    async def test_cost_patterns_scope_to_one_user(self, redis: fakeredis.FakeRedis) -> None:
        target = [f"{COST_BURST}:100", f"{COST_SUSTAINED}:100:period:0", f"{COST_BURST}:100:tm2"]
        # Prefix (1) and superstring (1000) ids must survive.
        others = [f"{COST_BURST}:1", f"{COST_BURST}:1000", f"{COST_BURST}:200"]
        await _seed(redis, *target, *others)

        deleted = await reset_keys(redis, cost_patterns("100"), dry_run=False)

        assert deleted == len(target)
        for k in target:
            assert not await _exists(redis, k)
        for k in others:
            assert await _exists(redis, k)

    async def test_request_patterns_reset_one_user(self, redis: fakeredis.FakeRedis) -> None:
        await _seed(redis, f"{REQ_BURST}:100", f"{REQ_SUSTAINED}:100", f"{REQ_BURST}:1000")

        deleted = await reset_keys(redis, request_patterns("100"), dry_run=False)

        assert deleted == 2
        assert not await _exists(redis, f"{REQ_BURST}:100")
        assert not await _exists(redis, f"{REQ_SUSTAINED}:100")
        # Exact match — "100" never touches "1000".
        assert await _exists(redis, f"{REQ_BURST}:1000")

    async def test_request_globs_do_not_match_cost_keys(self, redis: fakeredis.FakeRedis) -> None:
        await _seed(
            redis, f"{REQ_BURST}:100", f"{REQ_SUSTAINED}:100", f"{COST_BURST}:100", f"{COST_SUSTAINED}:100:period:0"
        )

        deleted = await reset_keys(redis, request_patterns(None), dry_run=False)

        assert deleted == 2
        assert await _exists(redis, f"{COST_BURST}:100")
        assert await _exists(redis, f"{COST_SUSTAINED}:100:period:0")

    async def test_product_patterns_reset_aggregate_pool(self, redis: fakeredis.FakeRedis) -> None:
        await _seed(redis, PRODUCT, f"{PRODUCT}:tm5", f"{COST_BURST}:100")

        deleted = await reset_keys(redis, product_patterns(), dry_run=False)

        assert deleted == 2
        assert not await _exists(redis, PRODUCT)
        assert not await _exists(redis, f"{PRODUCT}:tm5")
        assert await _exists(redis, f"{COST_BURST}:100")

    async def test_glob_metachars_in_user_id_do_not_expand(self, redis: fakeredis.FakeRedis) -> None:
        survivors = [f"{COST_BURST}:100", f"{COST_BURST}:1000", f"{REQ_BURST}:100"]
        await _seed(redis, *survivors)

        deleted = await reset_keys(redis, cost_patterns("10*") + request_patterns("10*"), dry_run=False)

        assert deleted == 0
        for k in survivors:
            assert await _exists(redis, k)

    @pytest.mark.parametrize("user_id", [None, "100"])
    async def test_dry_run_counts_without_deleting(self, redis: fakeredis.FakeRedis, user_id: str | None) -> None:
        await _seed(redis, f"{COST_BURST}:100", f"{COST_SUSTAINED}:100:period:0")

        deleted = await reset_keys(redis, cost_patterns(user_id), dry_run=True)

        assert deleted == 2
        assert await _exists(redis, f"{COST_BURST}:100")
        assert await _exists(redis, f"{COST_SUSTAINED}:100:period:0")

    async def test_returns_zero_when_no_keys(self, redis: fakeredis.FakeRedis) -> None:
        assert await reset_keys(redis, cost_patterns(None), dry_run=False) == 0

    async def test_leaves_unrelated_keys_untouched(self, redis: fakeredis.FakeRedis) -> None:
        survivors = [
            f"{COST_BURST.replace('posthog_code', 'other_product')}:100",
            "plan:posthog_code:100",
            "llm_gateway:cb:anthropic:v1:0",
            "some:other:key",
        ]
        await _seed(redis, *survivors)
        await _seed(redis, f"{COST_BURST}:100", f"{REQ_BURST}:100")

        deleted = await reset_keys(
            redis, cost_patterns(None) + request_patterns(None) + product_patterns(), dry_run=False
        )

        assert deleted == 2
        for k in survivors:
            assert await _exists(redis, k)


class TestPatternHelpers:
    def test_cost_patterns_all(self) -> None:
        assert cost_patterns(None) == (f"{COST_BURST}:*", f"{COST_SUSTAINED}:*")

    def test_request_patterns(self) -> None:
        assert request_patterns(None) == (f"{REQ_BURST}:*", f"{REQ_SUSTAINED}:*")
        assert request_patterns("100") == (f"{REQ_BURST}:100", f"{REQ_SUSTAINED}:100")

    def test_product_patterns(self) -> None:
        assert product_patterns() == (PRODUCT, f"{PRODUCT}:tm*")

    def test_non_empty_user_id_rejects_empty_string(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError):
            _non_empty_user_id("")
