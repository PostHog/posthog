from collections.abc import Iterator
from contextlib import contextmanager
from functools import cache

from django.conf import settings

from posthog.clickhouse.client.limit import RateLimit
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.utils import generate_short_id


@cache
def get_achievement_query_limiter() -> RateLimit:
    return RateLimit(
        max_concurrency=settings.WEB_ANALYTICS_ACHIEVEMENT_QUERY_MAX_CONCURRENCY,
        limit_name="web_analytics_achievements",
        get_task_name=lambda *args, **kwargs: "web_analytics:achievements:queries",
        get_task_id=lambda *args, **kwargs: generate_short_id(),
        ttl=15 * 60,
        allow_team_bypass=False,
    )


@contextmanager
def achievement_query_scope(team_id: int) -> Iterator[None]:
    with (
        tags_context(product=Product.WEB_ANALYTICS, feature=Feature.ENRICHMENT),
        get_achievement_query_limiter().run(team_id=team_id),
    ):
        yield
