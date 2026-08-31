from django.conf import settings
from django.core.cache import BaseCache, caches

import structlog
import posthoganalytics

from posthog.caching.tasks_redis_cache import TASKS_DEDICATED_CACHE_ALIAS
from posthog.redis import get_async_client, get_client

logger = structlog.get_logger(__name__)

# Evaluated once at run creation and pinned onto TaskRun.state["use_dedicated_stream"] so the
# SSE reader and the temporal worker always agree for a run's life (no split-brain on flag
# propagation or pod restarts).
TASKS_DEDICATED_REDIS_STREAMS_FLAG = "tasks-dedicated-redis-streams"


def evaluate_dedicated_stream_flag(*, organization_id: str, distinct_id: str) -> bool:
    # Gated on TASKS_REDIS_URL so the deciding process only opts a run into the dedicated
    # instance if it can itself reach it — a misconfigured pod fails safe to shared.
    if not settings.TASKS_REDIS_URL:
        return False
    try:
        return bool(
            posthoganalytics.feature_enabled(
                TASKS_DEDICATED_REDIS_STREAMS_FLAG,
                distinct_id=distinct_id,
                groups={"organization": organization_id},
                group_properties={"organization": {"id": organization_id}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        return False


def run_uses_dedicated_stream(state: dict | None) -> bool:
    # Defaults to shared so runs created before this rollout stay on the shared instance.
    return bool((state or {}).get("use_dedicated_stream", False))


def _tasks_stream_redis_url(use_dedicated: bool) -> str:
    dedicated = settings.TASKS_REDIS_URL
    if dedicated and use_dedicated:
        return dedicated
    return settings.REDIS_URL


def get_tasks_stream_redis_async(use_dedicated: bool = False):
    return get_async_client(_tasks_stream_redis_url(use_dedicated))


def get_tasks_stream_redis_sync(use_dedicated: bool = False):
    return get_client(_tasks_stream_redis_url(use_dedicated))


def get_tasks_cache() -> BaseCache:
    if settings.TASKS_REDIS_URL and TASKS_DEDICATED_CACHE_ALIAS in settings.CACHES:
        return caches[TASKS_DEDICATED_CACHE_ALIAS]
    return caches["default"]


def best_effort_cache_add(key: str, value: object, *, timeout: float | None, when_unavailable: bool = True) -> bool:
    """Best-effort ``cache.add`` for rate-limit and dedup keys.

    The write is an optimization, so a Redis failure (for example a failover that
    serves a read-only replica) must not escape and fail the caller. On failure
    the helper returns ``when_unavailable`` — by default ``True``, so a caller
    that guards with ``if not best_effort_cache_add(...): return`` proceeds as if
    the key was newly added rather than skipping its primary work.
    """
    try:
        return get_tasks_cache().add(key, value, timeout=timeout)
    except Exception:
        logger.warning("tasks.cache_add_failed", cache_key=key, exc_info=True)
        return when_unavailable


def best_effort_cache_set(key: str, value: object, *, timeout: float | None) -> None:
    """Best-effort ``cache.set`` for cached values. A Redis failure is swallowed and logged."""
    try:
        get_tasks_cache().set(key, value, timeout=timeout)
    except Exception:
        logger.warning("tasks.cache_set_failed", cache_key=key, exc_info=True)
