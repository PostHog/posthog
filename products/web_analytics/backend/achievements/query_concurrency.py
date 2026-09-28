from functools import cache

from django.conf import settings

from posthog.clickhouse.client.limit import RateLimit
from posthog.utils import generate_short_id


@cache
def get_achievement_query_limiter() -> RateLimit:
    return RateLimit(
        max_concurrency=settings.WEB_ANALYTICS_ACHIEVEMENT_QUERY_MAX_CONCURRENCY,
        limit_name="web_analytics_achievements",
        get_task_name=lambda *args, **kwargs: "web_analytics:achievements:queries",
        get_task_id=lambda *args, **kwargs: generate_short_id(),
        ttl=15 * 60,
        retry=0.25,
        retry_timeout=10.0,
        allow_team_bypass=False,
    )
