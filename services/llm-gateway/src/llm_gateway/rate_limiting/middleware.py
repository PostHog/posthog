from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.metrics.prometheus import RATE_LIMIT_EXCEEDED
from llm_gateway.rate_limiting.redis_limiter import RateLimiter


async def check_rate_limit(user: AuthenticatedUser, limiter: RateLimiter) -> bool:
    allowed, scope = await limiter.check(user.user_id)
    if not allowed and scope:
        RATE_LIMIT_EXCEEDED.labels(scope=scope).inc()
    return allowed
