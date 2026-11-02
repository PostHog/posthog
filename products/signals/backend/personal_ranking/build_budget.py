"""The daily limit on personal ranking builds that call the model, shared by every person in one region.

The `for_me` read spends one build here before it queues a build that may call the model. A scheduled caller
spends from the same bucket. Each region has its own Redis, so each region counts on its own.
"""

from django.conf import settings

import structlog

from posthog.token_bucket import BucketUnavailable, Budget, consume

from products.signals.backend.personal_ranking.config import PersonalRankingConfig

logger = structlog.get_logger(__name__)

_BUCKET_PREFIX = "personal_ranking_build_rate:shared"
# A build costs one token per hour of the day, and the bucket refills `max_builds_per_day` tokens an hour,
# so it refills exactly `max_builds_per_day` builds a day. A whole-token rate per build would round it up.
DAILY_BUILD_COST = 24


def _key() -> str:
    return f"{_BUCKET_PREFIX}:{settings.CLOUD_DEPLOYMENT or 'local'}"


def _budget(config: PersonalRankingConfig) -> Budget:
    return Budget(burst=config.max_builds_per_day * DAILY_BUILD_COST, per_hour=config.max_builds_per_day)


def spend_shared_build(config: PersonalRankingConfig) -> int | None:
    """Spend one build of the shared daily limit. Returns None when allowed, else the seconds until the next build."""
    decision = consume(_key(), _budget(config), cost=DAILY_BUILD_COST)
    if isinstance(decision, BucketUnavailable):
        # Fail open, like the per-person buckets, so an unreachable Redis does not hide the list.
        logger.warning("signals.personal_ranking.shared_build_bucket_unavailable")
        return None
    return None if decision.allowed else decision.retry_after
