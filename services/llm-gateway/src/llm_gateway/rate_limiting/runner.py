from __future__ import annotations

import asyncio

import structlog

from llm_gateway.metrics.prometheus import RATE_LIMIT_EXCEEDED
from llm_gateway.rate_limiting.throttles import Throttle, ThrottleContext, ThrottleResult

logger = structlog.get_logger(__name__)


class ThrottleRunner:
    def __init__(self, throttles: list[Throttle]):
        self._throttles = throttles

    async def check(self, context: ThrottleContext) -> ThrottleResult:
        results = await asyncio.gather(*[t.allow_request(context) for t in self._throttles])

        for throttle, result in zip(self._throttles, results, strict=True):
            if not result.allowed:
                scope = result.scope or throttle.scope
                RATE_LIMIT_EXCEEDED.labels(scope=scope).inc()
                logger.warning(
                    "throttle_denied",
                    user_id=context.user.user_id,
                    application_id=context.user.application_id,
                    product=context.product,
                    scope=scope,
                    status_code=result.status_code,
                )
                return result
        return ThrottleResult.allow()

    async def record_cost(self, context: ThrottleContext, cost: float) -> None:
        """Record cost after response completes."""
        from llm_gateway.rate_limiting.cost_throttles import CostThrottle

        for throttle in self._throttles:
            if isinstance(throttle, CostThrottle):
                await throttle.record_cost(context, cost)
