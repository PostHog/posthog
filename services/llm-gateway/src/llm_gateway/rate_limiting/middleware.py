import structlog

from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.metrics.prometheus import RATE_LIMIT_EXCEEDED
from llm_gateway.rate_limiting.redis_limiter import RateLimiter

logger = structlog.get_logger(__name__)


async def check_rate_limit(user: AuthenticatedUser, limiter: RateLimiter) -> tuple[bool, str | None]:
    """Check rate limit for user. Returns (allowed, exceeded_scope)."""
    allowed, scope = await limiter.check(user.user_id)
    if not allowed and scope:
        RATE_LIMIT_EXCEEDED.labels(scope=scope).inc()
        logger.warning("rate_limit_exceeded", user_id=user.user_id, scope=scope)
    return allowed, scope
