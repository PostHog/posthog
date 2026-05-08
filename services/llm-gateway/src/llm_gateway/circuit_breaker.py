from __future__ import annotations

import random
import time

import structlog
from redis.asyncio import Redis

logger = structlog.get_logger(__name__)


# A sliding window implemented as N fixed-width buckets. Each bucket stores a
# "S:F" string (successes:failures) and expires after the full window has elapsed.
# We sum the most recent N buckets to compute the failure rate.
BUCKET_WIDTH_SECONDS = 30
KEY_PREFIX = "llm_gateway:cb:anthropic"


class AnthropicCircuitBreaker:
    """Tracks the trailing Anthropic failure rate and decides when to bypass to Bedrock.

    The breaker is *open* when the trailing failure rate over `window_seconds` is at or
    above `failure_threshold`, provided we've seen at least `min_requests` in that window.
    While open, `should_bypass` returns True with probability `bypass_probability` so we
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
        field = "s" if success else "f"
        try:
            pipe = self.redis.pipeline()
            pipe.hincrby(key, field, 1)
            # TTL = window + one bucket so a bucket fully covers its slice before expiring.
            pipe.expire(key, self.window_seconds + BUCKET_WIDTH_SECONDS)
            await pipe.execute()
        except Exception:
            logger.exception("circuit_breaker_record_failed", success=success)

    async def get_stats(self) -> tuple[int, int]:
        """Return (total, failures) summed across the trailing window."""
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

    async def get_failure_rate(self) -> tuple[float, int]:
        total, failures = await self.get_stats()
        if total == 0:
            return 0.0, 0
        return failures / total, total

    async def is_open(self) -> tuple[bool, float, int]:
        """Return (open, failure_rate, total_requests_in_window)."""
        if not self.enabled:
            return False, 0.0, 0
        rate, total = await self.get_failure_rate()
        if total < self.min_requests:
            return False, rate, total
        return rate >= self.failure_threshold, rate, total

    async def should_bypass(self) -> tuple[bool, float, int]:
        """Decide whether to bypass Anthropic for a single request.

        Returns (bypass, failure_rate, total_requests_in_window). The caller is
        responsible for honoring the per-request `use_bedrock_fallback` opt-in
        before consulting this — the breaker only opens; it doesn't force fallback
        on callers that haven't opted in.
        """
        open_, rate, total = await self.is_open()
        if not open_:
            return False, rate, total
        return random.random() < self.bypass_probability, rate, total


_INSTANCE: AnthropicCircuitBreaker | None = None


def init_anthropic_circuit_breaker(redis: Redis[bytes] | None) -> AnthropicCircuitBreaker:
    from llm_gateway.config import get_settings

    settings = get_settings()
    global _INSTANCE
    _INSTANCE = AnthropicCircuitBreaker(
        redis=redis,
        failure_threshold=settings.anthropic_circuit_breaker_failure_threshold,
        window_seconds=settings.anthropic_circuit_breaker_window_seconds,
        bypass_probability=settings.anthropic_circuit_breaker_bypass_probability,
        min_requests=settings.anthropic_circuit_breaker_min_requests,
        enabled=settings.anthropic_circuit_breaker_enabled,
    )
    return _INSTANCE


def get_anthropic_circuit_breaker() -> AnthropicCircuitBreaker | None:
    return _INSTANCE


def set_anthropic_circuit_breaker(breaker: AnthropicCircuitBreaker | None) -> None:
    global _INSTANCE
    _INSTANCE = breaker
