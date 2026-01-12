from __future__ import annotations

import structlog

from llm_gateway.metrics.prometheus import RATE_LIMIT_EXCEEDED
from llm_gateway.rate_limiting.throttles import Throttle, ThrottleContext, ThrottleResult

logger = structlog.get_logger(__name__)


class ThrottleRunner:
    def __init__(self, throttles: list[Throttle]):
        self._throttles = throttles

    async def check(self, context: ThrottleContext) -> ThrottleResult:
        for throttle in self._throttles:
            result = await throttle.allow_request(context)
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
