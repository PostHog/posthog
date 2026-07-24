from __future__ import annotations

import time
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest
from fakeredis import aioredis as fakeredis

from llm_gateway.circuit_breaker import (
    BUCKET_WIDTH_SECONDS,
    KEY_PREFIX,
    AnthropicCircuitBreaker,
)
from llm_gateway.config import ModelCircuitBreakerPolicy


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
    model_policies: dict[str, ModelCircuitBreakerPolicy] | None = None,
    enabled: bool = True,
) -> AnthropicCircuitBreaker:
    return AnthropicCircuitBreaker(
        redis=redis,
        failure_threshold=failure_threshold,
        window_seconds=window_seconds,
        bypass_probability=bypass_probability,
        min_requests=min_requests,
        model_policies={"claude-fable-5": ModelCircuitBreakerPolicy(min_requests=5, cross_request_fallback=True)}
        if model_policies is None
        else model_policies,
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

    async def test_model_failures_are_not_diluted_by_healthy_models(
        self, fake_redis: fakeredis.FakeRedis, frozen_time: MagicMock
    ) -> None:
        breaker = make_breaker(fake_redis, min_requests=5, failure_threshold=0.25)
        for _ in range(5):
            await breaker.record_outcome(success=False, model="claude-fable-5")
        for _ in range(20):
            await breaker.record_outcome(success=True, model="claude-sonnet-4-6")

        with patch("llm_gateway.circuit_breaker.random.random", return_value=0.999):
            fable_decision = await breaker.evaluate("claude-fable-5")
        sonnet_decision = await breaker.evaluate("claude-sonnet-4-6")
        aggregate_decision = await breaker.evaluate()

        assert fable_decision.open is True
        assert fable_decision.bypass is True
        assert sonnet_decision.open is False
        assert aggregate_decision.open is False

    async def test_cross_request_policy_opens_on_first_failure_after_successes(
        self, fake_redis: fakeredis.FakeRedis, frozen_time: MagicMock
    ) -> None:
        breaker = make_breaker(
            fake_redis,
            model_policies={"claude-fable-5": ModelCircuitBreakerPolicy(min_requests=1, cross_request_fallback=True)},
        )
        for _ in range(4):
            await breaker.record_outcome(success=True, model="claude-fable-5")
        await breaker.record_outcome(success=False, model="claude-fable-5")

        decision = await breaker.evaluate("claude-fable-5")

        assert decision.open is True

    async def test_unconfigured_model_uses_only_aggregate_keys(
        self, fake_redis: fakeredis.FakeRedis, frozen_time: MagicMock
    ) -> None:
        breaker = make_breaker(
            fake_redis,
            min_requests=20,
            model_policies={"claude-fable-5": ModelCircuitBreakerPolicy(min_requests=5)},
        )
        unknown_model = "unknown-" + ("x" * 1_000)
        for _ in range(5):
            await breaker.record_outcome(success=False, model=unknown_model)

        decision = await breaker.evaluate(unknown_model)
        keys = await fake_redis.keys(f"{KEY_PREFIX}:*")

        assert decision.open is False
        assert decision.total_requests == 5
        assert all(b":aggregate:" in key for key in keys)

    @pytest.mark.parametrize(
        "model_policies",
        [
            {"claude-fable-5": {"min_requests": 0}},
            {"": {"min_requests": 5}},
            {"x" * 201: {"min_requests": 5}},
            {f"model-{index}": {"min_requests": 5} for index in range(51)},
        ],
    )
    def test_rejects_invalid_model_breaker_configuration(self, model_policies: dict[str, dict[str, int]]) -> None:
        from pydantic import ValidationError

        from llm_gateway.config import Settings

        with pytest.raises(ValidationError):
            Settings(anthropic_circuit_breaker_model_policies=model_policies)

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

    async def test_redis_failure_increments_error_counter(self, frozen_time: MagicMock) -> None:
        from llm_gateway.metrics.prometheus import ANTHROPIC_CIRCUIT_BREAKER_REDIS_ERRORS

        broken_redis = MagicMock()
        broken_redis.pipeline = MagicMock(side_effect=RuntimeError("redis down"))
        breaker = make_breaker(broken_redis)

        before_record = ANTHROPIC_CIRCUIT_BREAKER_REDIS_ERRORS.labels(op="record")._value.get()
        before_read = ANTHROPIC_CIRCUIT_BREAKER_REDIS_ERRORS.labels(op="read")._value.get()
        await breaker.record_outcome(success=False)
        await breaker._get_stats()
        assert ANTHROPIC_CIRCUIT_BREAKER_REDIS_ERRORS.labels(op="record")._value.get() == before_record + 1
        assert ANTHROPIC_CIRCUIT_BREAKER_REDIS_ERRORS.labels(op="read")._value.get() == before_read + 1

    async def test_redis_timeout_does_not_block(self) -> None:
        import asyncio as _asyncio

        slow_pipe = MagicMock()
        slow_pipe.hincrby = MagicMock(return_value=slow_pipe)
        slow_pipe.expire = MagicMock(return_value=slow_pipe)
        slow_pipe.hmget = MagicMock(return_value=slow_pipe)

        async def hang() -> object:
            await _asyncio.sleep(10.0)
            return []

        slow_pipe.execute = MagicMock(side_effect=hang)
        slow_redis = MagicMock()
        slow_redis.pipeline = MagicMock(return_value=slow_pipe)

        breaker = make_breaker(slow_redis)
        with patch("llm_gateway.circuit_breaker.REDIS_OP_TIMEOUT_SECONDS", 0.01):
            start = time.monotonic()
            await breaker.record_outcome(success=True)
            decision = await breaker.evaluate()
            elapsed = time.monotonic() - start
        assert elapsed < 1.0
        assert decision.total_requests == 0


class TestPublishGaugesLoop:
    async def test_publishes_gauges_then_cancels_cleanly(self, fake_redis: fakeredis.FakeRedis) -> None:
        from llm_gateway.circuit_breaker import _publish_anthropic_breaker_gauges
        from llm_gateway.metrics.prometheus import (
            ANTHROPIC_CIRCUIT_BREAKER_FAILURE_RATE,
            ANTHROPIC_CIRCUIT_BREAKER_OPEN,
            ANTHROPIC_CIRCUIT_BREAKER_WINDOW_REQUESTS,
            ANTHROPIC_MODEL_CIRCUIT_BREAKER_FAILURE_RATE,
            ANTHROPIC_MODEL_CIRCUIT_BREAKER_OPEN,
            ANTHROPIC_MODEL_CIRCUIT_BREAKER_WINDOW_REQUESTS,
        )

        breaker = make_breaker(fake_redis, min_requests=5, failure_threshold=0.25)
        for _ in range(15):
            await breaker.record_outcome(success=True, model="claude-fable-5")
        for _ in range(5):
            await breaker.record_outcome(success=False, model="claude-fable-5")

        original_pipeline = fake_redis.pipeline
        with patch.object(fake_redis, "pipeline", wraps=original_pipeline) as pipeline_calls:
            await _publish_anthropic_breaker_gauges(breaker)

        assert pipeline_calls.call_count == 1
        assert ANTHROPIC_CIRCUIT_BREAKER_OPEN._value.get() == 1
        assert ANTHROPIC_CIRCUIT_BREAKER_FAILURE_RATE._value.get() == pytest.approx(0.25)
        assert ANTHROPIC_CIRCUIT_BREAKER_WINDOW_REQUESTS._value.get() == 20
        assert ANTHROPIC_MODEL_CIRCUIT_BREAKER_OPEN.labels(model="claude-fable-5")._value.get() == 1
        assert ANTHROPIC_MODEL_CIRCUIT_BREAKER_FAILURE_RATE.labels(
            model="claude-fable-5"
        )._value.get() == pytest.approx(0.25)
        assert ANTHROPIC_MODEL_CIRCUIT_BREAKER_WINDOW_REQUESTS.labels(model="claude-fable-5")._value.get() == 20
