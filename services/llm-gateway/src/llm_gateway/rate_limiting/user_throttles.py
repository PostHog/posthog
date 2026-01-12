from __future__ import annotations

from llm_gateway.rate_limiting.throttles import RateThrottle, ThrottleContext


class UserBurstThrottle(RateThrottle):
    scope = "user_burst"
    rate = "500/minute"

    def get_cache_key(self, context: ThrottleContext) -> str:
        return f"user:{context.user.user_id}"


class UserSustainedThrottle(RateThrottle):
    scope = "user_sustained"
    rate = "10000/hour"

    def get_cache_key(self, context: ThrottleContext) -> str:
        return f"user:{context.user.user_id}"
