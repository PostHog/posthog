from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest
from fakeredis import aioredis as fakeredis

from llm_gateway.circuit_breaker import (
    BUCKET_WIDTH_SECONDS,
    AnthropicCircuitBreaker,
)


@pytest.fixture
def fake_redis() -> fakeredis.FakeRedis:
    return fakeredis.FakeRedis()


@pytest.fixture
def frozen_time() -> Iterator[MagicMock]:
    with patch("llm_gateway.circuit_breaker.time.time") as mock_time:
        mock_time.return_value = 1_000_000.0
        yield mock_time


def make_breaker(
    redis: fakeredis.FakeRedis | None,
    *,
    failure_threshold: float = 0.25,
    window_seconds: int = 300,
    bypass_probability: float = 0.9,
    min_requests: int = 5,
    enabled: bool = True,
) -> AnthropicCircuitBreaker:
    return AnthropicCircuitBreaker(
        redis=redis,
        failure_threshold=failure_threshold,
        window_seconds=window_seconds,
        bypass_probability=bypass_probability,
        min_requests=min_requests,
        enabled=enabled,
    )


class TestAnthropicCircuitBreaker:
    async def test_disabled_breaker_is_inert(self, fake_redis: fakeredis.FakeRedis, frozen_time: MagicMock) -> None:
        breaker = make_breaker(fake_redis, enabled=False)
        for _ in range(10):
            await breaker.record_outcome(success=False)
        decision = await breaker.evaluate()
        assert decision.bypass is False
        assert decision.open is False
        assert decision.failure_rate == 0.0
        assert decision.total_requests == 0

    async def test_no_redis_is_inert(self, frozen_time: MagicMock) -> None:
        breaker = make_breaker(None)
        await breaker.record_outcome(success=False)
        decision = await breaker.evaluate()
        assert decision.bypass is False
        assert decision.open is False

    async def test_below_min_requests_does_not_open(
        self, fake_redis: fakeredis.FakeRedis, frozen_time: MagicMock
    ) -> None:
        breaker = make_breaker(fake_redis, min_requests=10, failure_threshold=0.25)
        for _ in range(4):
            await breaker.record_outcome(success=False)
        decision = await breaker.evaluate()
        assert decision.open is False
        assert decision.bypass is False
        assert decision.failure_rate == 1.0
        assert decision.total_requests == 4

    async def test_opens_when_failure_rate_crosses_threshold(
        self, fake_redis: fakeredis.FakeRedis, frozen_time: MagicMock
    ) -> None:
        breaker = make_breaker(fake_redis, min_requests=5, failure_threshold=0.25)
        for _ in range(15):
            await breaker.record_outcome(success=True)
        decision = await breaker.evaluate()
        assert decision.open is False
        assert decision.failure_rate == 0.0

        for _ in range(5):
            await breaker.record_outcome(success=False)
        decision = await breaker.evaluate()
        assert decision.open is True
        assert decision.failure_rate == pytest.approx(0.25)
        assert decision.total_requests == 20

    async def test_closes_when_failure_rate_drops(
        self, fake_redis: fakeredis.FakeRedis, frozen_time: MagicMock
    ) -> None:
        breaker = make_breaker(fake_redis, min_requests=5, failure_threshold=0.25)
        for _ in range(5):
            await breaker.record_outcome(success=False)
        for _ in range(5):
            await breaker.record_outcome(success=True)
        decision = await breaker.evaluate()
        assert decision.open is True
        assert decision.failure_rate == 0.5

        for _ in range(50):
            await breaker.record_outcome(success=True)
        decision = await breaker.evaluate()
        assert decision.open is False
        assert decision.failure_rate < 0.25

    async def test_bypass_uses_probability_when_open(
        self, fake_redis: fakeredis.FakeRedis, frozen_time: MagicMock
    ) -> None:
        breaker = make_breaker(fake_redis, min_requests=5, failure_threshold=0.25, bypass_probability=0.9)
        for _ in range(10):
            await breaker.record_outcome(success=False)

        with patch("llm_gateway.circuit_breaker.random.random", return_value=0.5):
            decision = await breaker.evaluate()
            assert decision.bypass is True
            assert decision.open is True

        with patch("llm_gateway.circuit_breaker.random.random", return_value=0.95):
            decision = await breaker.evaluate()
            assert decision.bypass is False
            assert decision.open is True

    async def test_bypass_never_when_closed(self, fake_redis: fakeredis.FakeRedis, frozen_time: MagicMock) -> None:
        breaker = make_breaker(fake_redis, min_requests=5, failure_threshold=0.25, bypass_probability=0.9)
        for _ in range(20):
            await breaker.record_outcome(success=True)

        with patch("llm_gateway.circuit_breaker.random.random", return_value=0.0):
            decision = await breaker.evaluate()
            assert decision.bypass is False
            assert decision.open is False

    async def test_old_buckets_outside_window_excluded(self, fake_redis: fakeredis.FakeRedis) -> None:
        # window=300s with 30s buckets → 10 buckets retained.
        # Failures recorded 11 buckets ago should not count.
        breaker = make_breaker(fake_redis, min_requests=5, failure_threshold=0.25, window_seconds=300)
        with patch("llm_gateway.circuit_breaker.time.time", return_value=1_000_000.0):
            for _ in range(20):
                await breaker.record_outcome(success=False)

        far_future = 1_000_000.0 + (BUCKET_WIDTH_SECONDS * 11)
        with patch("llm_gateway.circuit_breaker.time.time", return_value=far_future):
            for _ in range(5):
                await breaker.record_outcome(success=True)
            decision = await breaker.evaluate()
            assert decision.total_requests == 5
            assert decision.failure_rate == 0.0
            assert decision.open is False

    async def test_redis_failure_is_swallowed(self, frozen_time: MagicMock) -> None:
        broken_redis = MagicMock()
        broken_redis.pipeline = MagicMock(side_effect=RuntimeError("redis down"))
        breaker = make_breaker(broken_redis)
        await breaker.record_outcome(success=False)
        decision = await breaker.evaluate()
        assert decision.bypass is False
        assert decision.open is False
        assert decision.failure_rate == 0.0
        assert decision.total_requests == 0
