from __future__ import annotations

from llm_gateway.products.config import get_product_config
from llm_gateway.rate_limiting.throttles import Throttle, ThrottleContext, ThrottleResult

# Hint the client to back off for a minute. A precise expiry timestamp is
# available upstream in Redis, but with Django's 30s in-process cache and the
# gateway's 30s resolver cache stacked on top, any computed retry window would
# be 0–60s stale anyway — a fixed minute is no worse and cuts the data
# plumbing.
_RETRY_AFTER_SECONDS = 60


class BillableCreditThrottle(Throttle):
    """Gate billable-product LLM calls on the team's AI credits balance.

    Reads ``ai_credits_exhausted`` from :class:`ThrottleContext`, pre-resolved
    by the dependency layer (see ``resolve_quota_status``).
    """

    scope = "billable_credits"

    async def allow_request(self, context: ThrottleContext) -> ThrottleResult:
        config = get_product_config(context.product)
        if not (config and config.billable):
            return ThrottleResult.allow()

        if not context.ai_credits_exhausted:
            return ThrottleResult.allow()

        return ThrottleResult.deny(
            detail=config.quota_exhausted_message,
            scope=self.scope,
            retry_after=_RETRY_AFTER_SECONDS,
        )
