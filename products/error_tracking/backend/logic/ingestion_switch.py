import time

import structlog
from redis.exceptions import RedisError

from posthog.exceptions_capture import capture_exception
from posthog.redis import get_client

from products.error_tracking.backend.models import ErrorTrackingSettings

logger = structlog.get_logger(__name__)

# Capture reads this sorted set and drops `$exception` events for every member. Members are project API tokens,
# scored with the time the project turned exception ingestion off. Keep the name in sync with
# `rust/capture/src/error_tracking_ingestion.rs`.
INGESTION_DISABLED_TOKENS_REDIS_KEY = "@posthog/error-tracking/ingestion-disabled-tokens"


def list_ingestion_disabled_api_tokens() -> list[str]:
    return list(
        ErrorTrackingSettings.objects.filter(ingestion_enabled=False)
        .order_by("team_id")
        .values_list("team__api_token", flat=True)
    )


def sync_team_ingestion_disabled_token(team_id: int) -> None:
    settings = ErrorTrackingSettings.objects.select_related("team").get(team_id=team_id)
    token = settings.team.api_token
    try:
        if settings.ingestion_enabled:
            get_client().zrem(INGESTION_DISABLED_TOKENS_REDIS_KEY, token)
        else:
            get_client().zadd(INGESTION_DISABLED_TOKENS_REDIS_KEY, {token: time.time()}, nx=True)
    except RedisError as error:
        # The settings row is already saved, and the reconcile task repairs the set within a minute.
        capture_exception(error)
        logger.warning("error_tracking_ingestion_switch_sync_failed", team_id=team_id, exc_info=True)


def reconcile_ingestion_disabled_tokens() -> None:
    expected = set(list_ingestion_disabled_api_tokens())
    client = get_client()
    current = {member.decode() for member in client.zrange(INGESTION_DISABLED_TOKENS_REDIS_KEY, 0, -1)}
    stale = current - expected
    missing = expected - current
    if not stale and not missing:
        return

    pipeline = client.pipeline()
    if stale:
        pipeline.zrem(INGESTION_DISABLED_TOKENS_REDIS_KEY, *stale)
    if missing:
        pipeline.zadd(INGESTION_DISABLED_TOKENS_REDIS_KEY, dict.fromkeys(missing, time.time()), nx=True)
    pipeline.execute()
    logger.info("error_tracking_ingestion_switch_reconciled", removed=len(stale), added=len(missing))
