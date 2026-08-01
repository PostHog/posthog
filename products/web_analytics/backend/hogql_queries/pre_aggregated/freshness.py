from datetime import UTC, datetime
from typing import Optional

import structlog

from posthog import redis
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tags_context

logger = structlog.get_logger(__name__)

WATERMARK_REDIS_PREFIX = "web_analytics:preagg_watermark:"
WATERMARK_CACHE_TTL_SECONDS = 5 * 60


def _watermark_cache_key(team_id: int) -> str:
    return f"{WATERMARK_REDIS_PREFIX}{team_id}"


def _fetch_watermark_from_clickhouse(team_id: int) -> Optional[datetime]:
    query = """
        SELECT max(period_bucket)
        FROM web_pre_aggregated_stats
        WHERE team_id = %(team_id)s
    """
    with tags_context(product=Product.WEB_ANALYTICS, feature=Feature.PREAGGREGATION):
        rows = sync_execute(query, {"team_id": team_id}, team_id=team_id)

    if not rows or rows[0][0] is None:
        return None

    max_bucket = rows[0][0]
    return max_bucket if max_bucket.tzinfo else max_bucket.replace(tzinfo=UTC)


def get_pre_aggregated_watermark(team_id: int) -> Optional[datetime]:
    """Returns the most recent `period_bucket` built for this team, cached briefly.

    Returns None when the watermark is unknown - either the team has no
    pre-aggregated data at all, or ClickHouse couldn't be reached - so callers
    can treat "unknown" the same as "not fresh enough" rather than assuming
    coverage that was never confirmed.
    """
    cache_key = _watermark_cache_key(team_id)

    try:
        cached = redis.get_client().get(cache_key)
        if cached is not None:
            return datetime.fromisoformat(cached.decode() if isinstance(cached, bytes) else cached)
    except Exception:
        logger.warning("web_analytics.preagg_watermark_cache_read_failed", team_id=team_id, exc_info=True)

    try:
        watermark = _fetch_watermark_from_clickhouse(team_id)
    except Exception:
        logger.warning("web_analytics.preagg_watermark_fetch_failed", team_id=team_id, exc_info=True)
        return None

    try:
        if watermark is not None:
            redis.get_client().set(cache_key, watermark.isoformat(), ex=WATERMARK_CACHE_TTL_SECONDS)
    except Exception:
        logger.warning("web_analytics.preagg_watermark_cache_write_failed", team_id=team_id, exc_info=True)

    return watermark
