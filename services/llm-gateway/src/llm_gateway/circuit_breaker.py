from __future__ import annotations

import asyncio
import math
import random
import time
from dataclasses import dataclass
from typing import Literal

import structlog
from redis.asyncio import Redis

from llm_gateway.config import ModelCircuitBreakerPolicy, get_settings

logger = structlog.get_logger(__name__)


BUCKET_WIDTH_SECONDS = 30
# Bump the prefix when bucket semantics change so rolling deploys cannot mix incompatible writes.
KEY_PREFIX = "llm_gateway:cb:anthropic:v2"
REDIS_OP_TIMEOUT_SECONDS = 0.1

_OutcomeField = Literal["s", "f"]


@dataclass(frozen=True)
class BreakerDecision:
    bypass: bool
    open: bool
    failure_rate: float
    total_requests: int


class AnthropicCircuitBreaker:
    """Tracks trailing Anthropic failure rates and decides when to bypass to Bedrock.

    Request routing evaluates configured models independently, while the unscoped aggregate is
    retained for gateway-wide metrics. Each model policy sets its request floor and failover mode;
    aggregate health uses `min_requests`. While open, the aggregate breaker keeps a fraction of
    probe traffic flowing to Anthropic, while configured model breakers bypass deterministically.
    """

    def __init__(
        self,
        redis: Redis[bytes] | None,
        failure_threshold: float,
        window_seconds: int,
        bypass_probability: float,
        min_requests: int,
        model_policies: dict[str, ModelCircuitBreakerPolicy],
        enabled: bool,
    ) -> None:
        self.redis = redis
        self.failure_threshold = failure_threshold
        self.window_seconds = window_seconds
        self.bypass_probability = bypass_probability
        self.min_requests = min_requests
        self.model_policies = model_policies
        self.enabled = enabled
        self._bucket_count = max(1, math.ceil(window_seconds / BUCKET_WIDTH_SECONDS))

    def _bucket_key(self, bucket_index: int, model: str | None = None) -> str:
        if model is None:
            return f"{KEY_PREFIX}:aggregate:{bucket_index}"
        return f"{KEY_PREFIX}:model:{model}:{bucket_index}"

    def _model_scope(self, model: str | None) -> str | None:
        return model if model in self.model_policies else None

    def uses_cross_request_fallback(self, model: str) -> bool:
        policy = self.model_policies.get(model)
        return bool(self.enabled and self.redis is not None and policy and policy.cross_request_fallback)

    def _current_bucket_index(self, now: float | None = None) -> int:
        return int((now if now is not None else time.time()) // BUCKET_WIDTH_SECONDS)

    async def record_outcome(self, *, success: bool, model: str | None = None) -> bool:
        if not self.enabled or self.redis is None:
            return False
        bucket = self._current_bucket_index()
        field: _OutcomeField = "s" if success else "f"
        try:
            # Pipeline atomicity is required: HINCRBY without EXPIRE leaks keys without TTL.
            pipe = self.redis.pipeline()
            keys = [self._bucket_key(bucket)]
            if model_scope := self._model_scope(model):
                keys.append(self._bucket_key(bucket, model_scope))
            for key in keys:
                pipe.hincrby(key, field, 1)
                pipe.expire(key, self.window_seconds + BUCKET_WIDTH_SECONDS)
            await asyncio.wait_for(pipe.execute(), timeout=REDIS_OP_TIMEOUT_SECONDS)
            return True
        except Exception as exc:
            from llm_gateway.metrics.prometheus import ANTHROPIC_CIRCUIT_BREAKER_REDIS_ERRORS

            ANTHROPIC_CIRCUIT_BREAKER_REDIS_ERRORS.labels(op="record").inc()
            logger.exception(
                "circuit_breaker_record_failed",
                success=success,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            return False

    async def _get_stats(self, model: str | None = None) -> tuple[int, int]:
        if not self.enabled or self.redis is None:
            return 0, 0
        current = self._current_bucket_index()
        model_scope = self._model_scope(model)
        keys = [self._bucket_key(current - offset, model_scope) for offset in range(self._bucket_count)]
        try:
            pipe = self.redis.pipeline()
            for key in keys:
                pipe.hmget(key, "s", "f")
            results = await asyncio.wait_for(pipe.execute(), timeout=REDIS_OP_TIMEOUT_SECONDS)
        except Exception:
            from llm_gateway.metrics.prometheus import ANTHROPIC_CIRCUIT_BREAKER_REDIS_ERRORS

            ANTHROPIC_CIRCUIT_BREAKER_REDIS_ERRORS.labels(op="read").inc()
            logger.exception("circuit_breaker_read_failed")
            return 0, 0

        successes = 0
        failures = 0
        for entry in results:
            if not entry:
                continue
            s_raw, f_raw = entry
            successes += int(s_raw or 0)
            failures += int(f_raw or 0)
        return successes + failures, failures

    def _decision(self, total: int, failures: int, model: str | None, *, choose_bypass: bool) -> BreakerDecision:
        rate = failures / total if total else 0.0
        policy = self.model_policies.get(model) if model is not None else None
        if policy is not None and policy.cross_request_fallback:
            is_open = failures >= policy.min_requests
        else:
            min_requests = policy.min_requests if policy is not None else self.min_requests
            is_open = total >= min_requests and rate >= self.failure_threshold
        if not is_open:
            return BreakerDecision(bypass=False, open=False, failure_rate=rate, total_requests=total)
        bypass_probability = 1.0 if policy is not None else self.bypass_probability
        bypass = choose_bypass and random.random() < bypass_probability
        return BreakerDecision(bypass=bypass, open=True, failure_rate=rate, total_requests=total)

    async def snapshot(self) -> dict[str | None, BreakerDecision]:
        scopes: list[str | None] = [None, *self.model_policies]
        if not self.enabled or self.redis is None:
            return {scope: BreakerDecision(False, False, 0.0, 0) for scope in scopes}

        current = self._current_bucket_index()
        pipe = self.redis.pipeline()
        for scope in scopes:
            for offset in range(self._bucket_count):
                pipe.hmget(self._bucket_key(current - offset, scope), "s", "f")
        try:
            results = await asyncio.wait_for(pipe.execute(), timeout=REDIS_OP_TIMEOUT_SECONDS)
        except Exception:
            from llm_gateway.metrics.prometheus import ANTHROPIC_CIRCUIT_BREAKER_REDIS_ERRORS

            ANTHROPIC_CIRCUIT_BREAKER_REDIS_ERRORS.labels(op="read").inc()
            logger.exception("circuit_breaker_read_failed")
            return {scope: BreakerDecision(False, False, 0.0, 0) for scope in scopes}

        decisions: dict[str | None, BreakerDecision] = {}
        for index, scope in enumerate(scopes):
            entries = results[index * self._bucket_count : (index + 1) * self._bucket_count]
            successes = sum(int(entry[0] or 0) for entry in entries if entry)
            failures = sum(int(entry[1] or 0) for entry in entries if entry)
            decisions[scope] = self._decision(successes + failures, failures, scope, choose_bypass=False)
        return decisions

    async def evaluate(self, model: str | None = None) -> BreakerDecision:
        """Single Redis read producing both the open/closed state and the per-request bypass decision.

        Caller is responsible for honoring the per-request `use_bedrock_fallback` opt-in
        before consulting this — the breaker only opens; it doesn't force fallback on
        callers that haven't opted in.
        """
        if not self.enabled:
            return BreakerDecision(bypass=False, open=False, failure_rate=0.0, total_requests=0)

        model_scope = self._model_scope(model)
        total, failures = await self._get_stats(model_scope)
        return self._decision(total, failures, model_scope, choose_bypass=True)


def build_anthropic_circuit_breaker(redis: Redis[bytes] | None) -> AnthropicCircuitBreaker:
    settings = get_settings()
    return AnthropicCircuitBreaker(
        redis=redis,
        failure_threshold=settings.anthropic_circuit_breaker_failure_threshold,
        window_seconds=settings.anthropic_circuit_breaker_window_seconds,
        bypass_probability=settings.anthropic_circuit_breaker_bypass_probability,
        min_requests=settings.anthropic_circuit_breaker_min_requests,
        model_policies=settings.anthropic_circuit_breaker_model_policies,
        enabled=settings.anthropic_circuit_breaker_enabled,
    )


async def _publish_anthropic_breaker_gauges(breaker: AnthropicCircuitBreaker) -> None:
    from llm_gateway.metrics.prometheus import (
        ANTHROPIC_CIRCUIT_BREAKER_FAILURE_RATE,
        ANTHROPIC_CIRCUIT_BREAKER_OPEN,
        ANTHROPIC_CIRCUIT_BREAKER_WINDOW_REQUESTS,
        ANTHROPIC_MODEL_CIRCUIT_BREAKER_FAILURE_RATE,
        ANTHROPIC_MODEL_CIRCUIT_BREAKER_OPEN,
        ANTHROPIC_MODEL_CIRCUIT_BREAKER_WINDOW_REQUESTS,
    )

    decisions = await breaker.snapshot()
    decision = decisions[None]
    ANTHROPIC_CIRCUIT_BREAKER_OPEN.set(1 if decision.open else 0)
    ANTHROPIC_CIRCUIT_BREAKER_FAILURE_RATE.set(decision.failure_rate)
    ANTHROPIC_CIRCUIT_BREAKER_WINDOW_REQUESTS.set(decision.total_requests)
    for model in breaker.model_policies:
        model_decision = decisions[model]
        ANTHROPIC_MODEL_CIRCUIT_BREAKER_OPEN.labels(model=model).set(1 if model_decision.open else 0)
        ANTHROPIC_MODEL_CIRCUIT_BREAKER_FAILURE_RATE.labels(model=model).set(model_decision.failure_rate)
        ANTHROPIC_MODEL_CIRCUIT_BREAKER_WINDOW_REQUESTS.labels(model=model).set(model_decision.total_requests)


async def publish_anthropic_breaker_gauges_loop(
    breaker: AnthropicCircuitBreaker,
    interval_seconds: int = 5,
) -> None:
    """Refresh breaker gauges outside the request hot path, including while traffic is idle."""
    while True:
        try:
            await _publish_anthropic_breaker_gauges(breaker)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("circuit_breaker_gauge_publish_failed")
        await asyncio.sleep(interval_seconds)
