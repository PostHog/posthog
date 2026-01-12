from __future__ import annotations

from llm_gateway.rate_limiting.throttles import RateThrottle, ThrottleContext


class GlobalBurstThrottle(RateThrottle):
    scope = "global_burst"
    rate = "2000/minute"

    def get_cache_key(self, context: ThrottleContext) -> str:
        return "global"


class GlobalSustainedThrottle(RateThrottle):
    scope = "global_sustained"
    rate = "100000/hour"

    def get_cache_key(self, context: ThrottleContext) -> str:
        return "global"
