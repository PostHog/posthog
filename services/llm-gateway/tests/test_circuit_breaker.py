from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

from llm_gateway.circuit_breaker import (
    BUCKET_WIDTH_SECONDS,
    AnthropicCircuitBreaker,
)


class _FakeRedis:
    """Minimal in-memory stand-in that mimics the redis.asyncio surface the breaker uses."""

    def __init__(self) -> None:
        self._hashes: dict[str, dict[str, int]] = {}

    def pipeline(self) -> _FakePipeline:
        return _FakePipeline(self)


class _FakePipeline:
    def __init__(self, redis: _FakeRedis) -> None:
        self._redis = redis
        self._ops: list[tuple[str, tuple]] = []

    def hincrby(self, key: str, field: str, amount: int) -> _FakePipeline:
        self._ops.append(("hincrby", (key, field, amount)))
        return self

    def expire(self, key: str, seconds: int) -> _FakePipeline:
        self._ops.append(("expire", (key, seconds)))
        return self

    def hmget(self, key: str, *fields: str) -> _FakePipeline:
        self._ops.append(("hmget", (key, fields)))
        return self

    async def execute(self) -> list:
        results: list = []
        for op, args in self._ops:
            if op == "hincrby":
                key, field, amount = args
                bucket = self._redis._hashes.setdefault(key, {})
                bucket[field] = bucket.get(field, 0) + amount
                results.append(bucket[field])
            elif op == "expire":
                results.append(True)
            elif op == "hmget":
                key, fields = args
                bucket = self._redis._hashes.get(key, {})
                results.append([str(bucket[f]).encode() if f in bucket else None for f in fields])
        return results


@pytest.fixture
def fake_redis() -> _FakeRedis:
    return _FakeRedis()


@pytest.fixture
def frozen_time() -> Iterator[MagicMock]:
    with patch("llm_gateway.circuit_breaker.time.time") as mock_time:
        mock_time.return_value = 1_000_000.0
        yield mock_time


def make_breaker(
    redis: _FakeRedis | None,
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
    @pytest.mark.asyncio
    async def test_disabled_breaker_is_inert(self, fake_redis: _FakeRedis, frozen_time: MagicMock) -> None:
        breaker = make_breaker(fake_redis, enabled=False)
        await breaker.record_outcome(success=False)
        for _ in range(10):
            await breaker.record_outcome(success=False)
        bypass, rate, total = await breaker.should_bypass()
        assert bypass is False
        assert rate == 0.0
        assert total == 0

    @pytest.mark.asyncio
    async def test_no_redis_is_inert(self, frozen_time: MagicMock) -> None:
        breaker = make_breaker(None)
        await breaker.record_outcome(success=False)
        bypass, rate, total = await breaker.should_bypass()
        assert bypass is False
        assert rate == 0.0
        assert total == 0

    @pytest.mark.asyncio
    async def test_below_min_requests_does_not_open(self, fake_redis: _FakeRedis, frozen_time: MagicMock) -> None:
        breaker = make_breaker(fake_redis, min_requests=10, failure_threshold=0.25)
        # 4 failures, 0 successes — 100% failure rate but only 4 observations.
        for _ in range(4):
            await breaker.record_outcome(success=False)
        open_, rate, total = await breaker.is_open()
        assert open_ is False
        assert rate == 1.0
        assert total == 4

    @pytest.mark.asyncio
    async def test_opens_when_failure_rate_crosses_threshold(
        self, fake_redis: _FakeRedis, frozen_time: MagicMock
    ) -> None:
        breaker = make_breaker(fake_redis, min_requests=5, failure_threshold=0.25)
        for _ in range(15):
            await breaker.record_outcome(success=True)
        # 15 success, 0 failures → 0% rate, closed
        open_, rate, _ = await breaker.is_open()
        assert open_ is False
        assert rate == 0.0

        for _ in range(5):
            await breaker.record_outcome(success=False)
        # 15 success, 5 failures → 25% rate (>=), open
        open_, rate, total = await breaker.is_open()
        assert open_ is True
        assert rate == pytest.approx(0.25)
        assert total == 20

    @pytest.mark.asyncio
    async def test_closes_when_failure_rate_drops(self, fake_redis: _FakeRedis, frozen_time: MagicMock) -> None:
        breaker = make_breaker(fake_redis, min_requests=5, failure_threshold=0.25)
        for _ in range(5):
            await breaker.record_outcome(success=False)
        for _ in range(5):
            await breaker.record_outcome(success=True)
        open_, rate, _ = await breaker.is_open()
        assert open_ is True
        assert rate == 0.5

        for _ in range(50):
            await breaker.record_outcome(success=True)
        open_, rate, _ = await breaker.is_open()
        assert open_ is False
        # 5 failures / 60 total ≈ 0.083
        assert rate < 0.25

    @pytest.mark.asyncio
    async def test_should_bypass_uses_probability_when_open(
        self, fake_redis: _FakeRedis, frozen_time: MagicMock
    ) -> None:
        breaker = make_breaker(fake_redis, min_requests=5, failure_threshold=0.25, bypass_probability=0.9)
        for _ in range(10):
            await breaker.record_outcome(success=False)

        with patch("llm_gateway.circuit_breaker.random.random", return_value=0.5):
            bypass, _, _ = await breaker.should_bypass()
            assert bypass is True

        with patch("llm_gateway.circuit_breaker.random.random", return_value=0.95):
            bypass, _, _ = await breaker.should_bypass()
            assert bypass is False

    @pytest.mark.asyncio
    async def test_should_bypass_never_when_closed(self, fake_redis: _FakeRedis, frozen_time: MagicMock) -> None:
        breaker = make_breaker(fake_redis, min_requests=5, failure_threshold=0.25, bypass_probability=0.9)
        for _ in range(20):
            await breaker.record_outcome(success=True)

        with patch("llm_gateway.circuit_breaker.random.random", return_value=0.0):
            bypass, _, _ = await breaker.should_bypass()
            assert bypass is False

    @pytest.mark.asyncio
    async def test_old_buckets_outside_window_excluded(self, fake_redis: _FakeRedis) -> None:
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
            open_, rate, total = await breaker.is_open()
            assert total == 5
            assert rate == 0.0
            assert open_ is False

    @pytest.mark.asyncio
    async def test_redis_failure_is_swallowed(self, frozen_time: MagicMock) -> None:
        broken_redis = MagicMock()
        broken_redis.pipeline = MagicMock(side_effect=RuntimeError("redis down"))
        breaker = make_breaker(broken_redis)
        # Must not raise.
        await breaker.record_outcome(success=False)
        bypass, rate, total = await breaker.should_bypass()
        assert bypass is False
        assert rate == 0.0
        assert total == 0
