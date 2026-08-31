from typing import Any

from django.conf import settings
from django.core.cache import BaseCache, caches
from django.core.cache.backends.base import DEFAULT_TIMEOUT

import structlog
import posthoganalytics
import redis.exceptions
from django_redis.exceptions import ConnectionInterrupted
from posthoganalytics import capture_exception

from posthog.caching.tasks_redis_cache import TASKS_DEDICATED_CACHE_ALIAS
from posthog.redis import get_async_client, get_client

logger = structlog.get_logger(__name__)

# Redis/transport failures a tasks cache operation degrades on instead of surfacing a 500.
# django-redis wraps the underlying redis error in ConnectionInterrupted; the raw redis errors
# (and the builtin socket errors under OSError) are caught too in case a backend raises them
# directly. Mirrors posthog/storage/hypercache.py.
_TASKS_CACHE_ERRORS = (
    ConnectionInterrupted,
    redis.exceptions.RedisError,
    ConnectionError,
    TimeoutError,
    OSError,
)

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


# The tasks cache is a speed layer: every value it holds can be recomputed or safely skipped.
# A loading Redis instance raises BusyLoadingError on read, which django-redis wraps in
# ConnectionInterrupted. Without a guard that error propagates out of the request handler as a
# 500. These helpers degrade a Redis blip to a cache miss so request-path reads and writes keep
# working while Redis finishes loading.


def tasks_cache_get(key: str, default: Any = None) -> Any:
    try:
        return get_tasks_cache().get(key, default)
    except _TASKS_CACHE_ERRORS as e:
        capture_exception(e)
        return default


def tasks_cache_set(key: str, value: Any, timeout: Any = DEFAULT_TIMEOUT) -> bool:
    """Returns whether the write reached Redis; a blip degrades to no write."""
    try:
        get_tasks_cache().set(key, value, timeout=timeout)
        return True
    except _TASKS_CACHE_ERRORS as e:
        capture_exception(e)
        return False


def tasks_cache_add(key: str, value: Any, timeout: Any = DEFAULT_TIMEOUT) -> bool:
    """Reserve a key if absent. A blip returns False, so callers that gate a one-shot side
    effect on the reservation skip it rather than fire without a throttle."""
    try:
        return get_tasks_cache().add(key, value, timeout=timeout)
    except _TASKS_CACHE_ERRORS as e:
        capture_exception(e)
        return False


def tasks_cache_delete(key: str) -> None:
    try:
        get_tasks_cache().delete(key)
    except _TASKS_CACHE_ERRORS as e:
        capture_exception(e)


def tasks_cache_delete_many(keys: list[str]) -> None:
    try:
        get_tasks_cache().delete_many(keys)
    except _TASKS_CACHE_ERRORS as e:
        capture_exception(e)
