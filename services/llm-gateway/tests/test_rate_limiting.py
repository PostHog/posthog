import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from fakeredis import aioredis as fakeredis
from fastapi.testclient import TestClient

from llm_gateway.rate_limiting.redis_limiter import RateLimiter
from llm_gateway.rate_limiting.throttles import Throttle, ThrottleContext, ThrottleResult
from llm_gateway.rate_limiting.token_bucket import TokenBucketLimiter
from tests.conftest import create_test_app


class TestTokenBucketLimiter:
    @pytest.mark.parametrize(
        "rate,capacity,consume_count,expected_results",
        [
            pytest.param(0.0, 3.0, 5, [True, True, True, False, False], id="exhaust_bucket_capacity_3"),
            pytest.param(0.0, 1.0, 3, [True, False, False], id="exhaust_bucket_capacity_1"),
            pytest.param(1000.0, 100.0, 5, [True] * 5, id="high_rate_replenishes"),
            pytest.param(0.0, 5.0, 5, [True] * 5, id="exact_capacity_consumption"),
        ],
    )
    def test_consumption_patterns(
        self,
        rate: float,
        capacity: float,
        consume_count: int,
        expected_results: list[bool],
    ) -> None:
        limiter = TokenBucketLimiter(rate=rate, capacity=capacity)
        results = [limiter.consume("user1") for _ in range(consume_count)]
        assert results == expected_results

    @pytest.mark.parametrize(
        "tokens_to_consume,capacity,should_succeed",
        [
            pytest.param(5.0, 10.0, True, id="consume_half_capacity"),
            pytest.param(10.0, 10.0, True, id="consume_full_capacity"),
            pytest.param(11.0, 10.0, False, id="consume_over_capacity"),
            pytest.param(0.0, 10.0, True, id="consume_zero"),
        ],
    )
    def test_multi_token_consumption(
        self,
        tokens_to_consume: float,
        capacity: float,
        should_succeed: bool,
    ) -> None:
        limiter = TokenBucketLimiter(rate=0.0, capacity=capacity)
        assert limiter.consume("user1", tokens=tokens_to_consume) is should_succeed

    def test_independent_keys(self) -> None:
        limiter = TokenBucketLimiter(rate=0.0, capacity=1.0)

        assert limiter.consume("user1") is True
        assert limiter.consume("user1") is False
        assert limiter.consume("user2") is True
        assert limiter.consume("user2") is False

    def test_clear_resets_all_buckets(self) -> None:
        limiter = TokenBucketLimiter(rate=0.0, capacity=1.0)

        limiter.consume("user1")
        limiter.consume("user2")
        assert limiter.consume("user1") is False
        assert limiter.consume("user2") is False

        limiter.clear()

        assert limiter.consume("user1") is True
        assert limiter.consume("user2") is True

    def test_tokens_replenish_over_time(self) -> None:
        limiter = TokenBucketLimiter(rate=10.0, capacity=1.0)

        assert limiter.consume("user1") is True
        assert limiter.consume("user1") is False

        time.sleep(0.15)

        assert limiter.consume("user1") is True

    def test_partial_replenishment(self) -> None:
        limiter = TokenBucketLimiter(rate=10.0, capacity=2.0)

        assert limiter.consume("user1", tokens=2.0) is True
        assert limiter.consume("user1") is False

        time.sleep(0.1)

        assert limiter.consume("user1") is True
        assert limiter.consume("user1") is False


class TestRateLimiter:
    @pytest.fixture
    def fake_redis(self) -> fakeredis.FakeRedis:
        return fakeredis.FakeRedis()

    @pytest.mark.asyncio
    async def test_local_only_when_no_redis(self) -> None:
        limiter = RateLimiter(
            redis=None,
            burst_limit=2,
            burst_window=60,
            sustained_limit=10,
            sustained_window=3600,
        )

        allowed, scope = await limiter.check(user_id=1)
        assert allowed is True
        assert scope is None

        await limiter.check(user_id=1)
        allowed, scope = await limiter.check(user_id=1)
        assert allowed is False
        assert scope == "burst"

    @pytest.mark.asyncio
    async def test_redis_rate_limiting(self, fake_redis: fakeredis.FakeRedis) -> None:
        limiter = RateLimiter(
            redis=fake_redis,
            burst_limit=2,
            burst_window=60,
            sustained_limit=10,
            sustained_window=3600,
        )

        allowed, _ = await limiter.check(user_id=1)
        assert allowed is True

        await limiter.check(user_id=1)
        allowed, scope = await limiter.check(user_id=1)
        assert allowed is False
        assert scope == "burst"

    @pytest.mark.asyncio
    async def test_redis_keys_are_set_with_expiry(self, fake_redis: fakeredis.FakeRedis) -> None:
        limiter = RateLimiter(
            redis=fake_redis,
            burst_limit=100,
            burst_window=60,
            sustained_limit=1000,
            sustained_window=3600,
        )

        await limiter.check(user_id=123)

        burst_ttl = await fake_redis.ttl("ratelimit:burst:123")
        sustained_ttl = await fake_redis.ttl("ratelimit:sustained:123")

        assert 0 < burst_ttl <= 60
        assert 0 < sustained_ttl <= 3600

    @pytest.mark.asyncio
    async def test_fallback_to_local_on_redis_error(self) -> None:
        mock_redis = MagicMock()
        mock_redis.incr = AsyncMock(side_effect=Exception("Redis connection failed"))

        limiter = RateLimiter(
            redis=mock_redis,
            burst_limit=2,
            burst_window=60,
            sustained_limit=10,
            sustained_window=3600,
        )

        allowed, scope = await limiter.check(user_id=1)
        assert allowed is True
        assert scope is None

    @pytest.mark.asyncio
    async def test_independent_users(self, fake_redis: fakeredis.FakeRedis) -> None:
        limiter = RateLimiter(
            redis=fake_redis,
            burst_limit=1,
            burst_window=60,
            sustained_limit=10,
            sustained_window=3600,
        )

        allowed1, _ = await limiter.check(user_id=1)
        allowed2, _ = await limiter.check(user_id=2)

        assert allowed1 is True
        assert allowed2 is True

        denied1, _ = await limiter.check(user_id=1)
        denied2, _ = await limiter.check(user_id=2)

        assert denied1 is False
        assert denied2 is False

    @pytest.mark.asyncio
    async def test_sustained_limit_after_burst_ok(self, fake_redis: fakeredis.FakeRedis) -> None:
        limiter = RateLimiter(
            redis=fake_redis,
            burst_limit=100,
            burst_window=60,
            sustained_limit=2,
            sustained_window=3600,
        )

        await limiter.check(user_id=1)
        await limiter.check(user_id=1)
        allowed, scope = await limiter.check(user_id=1)

        assert allowed is False
        assert scope == "sustained"


class TestRateLimitResponseHeaders:
    def test_429_includes_retry_after_header_and_structured_error(self, mock_db_pool: MagicMock) -> None:
        class AlwaysDenyThrottle(Throttle):
            scope = "test_throttle"

            async def allow_request(self, context: ThrottleContext) -> ThrottleResult:
                return ThrottleResult.deny(
                    detail=f"Input token rate limit exceeded for model {context.model}",
                    scope=self.scope,
                    retry_after=3600,
                )

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "id": "key_id",
                "user_id": 1,
                "scopes": ["llm_gateway:read"],
                "current_team_id": 1,
            }
        )
        mock_db_pool.acquire = AsyncMock(return_value=conn)

        app = create_test_app(mock_db_pool, throttles=[AlwaysDenyThrottle()])

        with TestClient(app) as client:
            body = {"model": "gpt-4", "messages": [{"role": "user", "content": "Hi"}]}
            headers = {"Authorization": "Bearer phx_test_key"}
            response = client.post("/v1/chat/completions", json=body, headers=headers)

            assert response.status_code == 429
            assert response.headers["retry-after"] == "3600"
            assert response.json() == {
                "detail": {
                    "error": {
                        "message": "Rate limit exceeded",
                        "type": "rate_limit_error",
                        "reason": "Input token rate limit exceeded for model gpt-4",
                    }
                }
            }
