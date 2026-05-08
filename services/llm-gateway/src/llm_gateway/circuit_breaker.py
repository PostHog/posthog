from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Literal

import structlog
from redis.asyncio import Redis

from llm_gateway.config import get_settings

logger = structlog.get_logger(__name__)


BUCKET_WIDTH_SECONDS = 30
KEY_PREFIX = "llm_gateway:cb:anthropic"

_OutcomeField = Literal["s", "f"]


@dataclass(frozen=True)
class BreakerDecision:
    bypass: bool
    open: bool
    failure_rate: float
    total_requests: int


class AnthropicCircuitBreaker:
    """Tracks the trailing Anthropic failure rate and decides when to bypass to Bedrock.

    The breaker is *open* when the trailing failure rate over `window_seconds` is at or
    above `failure_threshold`, provided we've seen at least `min_requests` in that window.
    While open, `evaluate` flags `bypass=True` with probability `bypass_probability` so we
    keep a fraction of probe traffic flowing to Anthropic to detect recovery.
    """

    def __init__(
        self,
        redis: Redis[bytes] | None,
        failure_threshold: float,
        window_seconds: int,
        bypass_probability: float,
        min_requests: int,
        enabled: bool,
    ) -> None:
        self.redis = redis
        self.failure_threshold = failure_threshold
        self.window_seconds = window_seconds
        self.bypass_probability = bypass_probability
        self.min_requests = min_requests
        self.enabled = enabled
        self._bucket_count = max(1, window_seconds // BUCKET_WIDTH_SECONDS)

    def _bucket_key(self, bucket_index: int) -> str:
        return f"{KEY_PREFIX}:{bucket_index}"

    def _current_bucket_index(self, now: float | None = None) -> int:
        return int((now if now is not None else time.time()) // BUCKET_WIDTH_SECONDS)

    async def record_outcome(self, *, success: bool) -> None:
        if not self.enabled or self.redis is None:
            return
        bucket = self._current_bucket_index()
        key = self._bucket_key(bucket)
        field: _OutcomeField = "s" if success else "f"
        try:
            pipe = self.redis.pipeline()
            pipe.hincrby(key, field, 1)
            # TTL = window + one bucket so a bucket fully covers its slice before expiring.
            pipe.expire(key, self.window_seconds + BUCKET_WIDTH_SECONDS)
            await pipe.execute()
        except Exception:
            logger.exception("circuit_breaker_record_failed", success=success)

    async def _get_stats(self) -> tuple[int, int]:
        if not self.enabled or self.redis is None:
            return 0, 0
        current = self._current_bucket_index()
        keys = [self._bucket_key(current - offset) for offset in range(self._bucket_count)]
        try:
            pipe = self.redis.pipeline()
            for key in keys:
                pipe.hmget(key, "s", "f")
            results = await pipe.execute()
        except Exception:
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

    async def evaluate(self) -> BreakerDecision:
        """Single Redis read producing both the open/closed state and the per-request bypass decision.

        Caller is responsible for honoring the per-request `use_bedrock_fallback` opt-in
        before consulting this — the breaker only opens; it doesn't force fallback on
        callers that haven't opted in.
        """
        if not self.enabled:
            return BreakerDecision(bypass=False, open=False, failure_rate=0.0, total_requests=0)

        total, failures = await self._get_stats()
        rate = failures / total if total else 0.0

        if total < self.min_requests or rate < self.failure_threshold:
            return BreakerDecision(bypass=False, open=False, failure_rate=rate, total_requests=total)

        bypass = random.random() < self.bypass_probability
        return BreakerDecision(bypass=bypass, open=True, failure_rate=rate, total_requests=total)


def build_anthropic_circuit_breaker(redis: Redis[bytes] | None) -> AnthropicCircuitBreaker:
    settings = get_settings()
    return AnthropicCircuitBreaker(
        redis=redis,
        failure_threshold=settings.anthropic_circuit_breaker_failure_threshold,
        window_seconds=settings.anthropic_circuit_breaker_window_seconds,
        bypass_probability=settings.anthropic_circuit_breaker_bypass_probability,
        min_requests=settings.anthropic_circuit_breaker_min_requests,
        enabled=settings.anthropic_circuit_breaker_enabled,
    )
