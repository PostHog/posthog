from typing import Any

from django.conf import settings
from django.core.cache import BaseCache, caches

import posthoganalytics
import redis.exceptions
from django_redis.exceptions import ConnectionInterrupted
from posthoganalytics import capture_exception

from posthog.caching.tasks_redis_cache import TASKS_DEDICATED_CACHE_ALIAS
from posthog.redis import get_async_client, get_client

# Redis/transport failures a best-effort cache call degrades on. django-redis wraps the raw
# redis error in ConnectionInterrupted; we also catch the raw redis errors and the builtin
# socket errors under OSError in case a backend surfaces them directly. Mirrors
# posthog/storage/hypercache.py.
_REDIS_ERRORS = (
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


def tasks_cache_get(key: str, default: Any = None) -> Any:
    """Best-effort ``cache.get``. Returns ``default`` on a redis failure instead of raising, so a
    redis blip cannot 500 a request that only reads an optional cached value."""
    try:
        return get_tasks_cache().get(key, default)
    except _REDIS_ERRORS as e:
        capture_exception(e)
        return default


def tasks_cache_set(key: str, value: Any, timeout: int | None = None) -> bool:
    """Best-effort ``cache.set``. Returns whether the write landed; a redis failure degrades to
    ``False`` instead of raising."""
    try:
        get_tasks_cache().set(key, value, timeout=timeout)
        return True
    except _REDIS_ERRORS as e:
        capture_exception(e)
        return False


def tasks_cache_add(key: str, value: Any, timeout: int | None = None, *, on_error: bool = True) -> bool:
    """Best-effort ``cache.add`` used as a dedup/cooldown guard. Returns True when the key was newly
    added (the caller should proceed), False when it already existed. A redis failure degrades to
    ``on_error`` instead of raising; callers pass ``on_error=True`` to keep proceeding when the
    guard cannot be checked."""
    try:
        return bool(get_tasks_cache().add(key, value, timeout=timeout))
    except _REDIS_ERRORS as e:
        capture_exception(e)
        return on_error
