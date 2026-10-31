from django.conf import settings
from django.core.cache import BaseCache, caches

from posthog.caching.tasks_redis_cache import TASKS_DEDICATED_CACHE_ALIAS
from posthog.redis import get_async_client, get_client


def dedicated_stream_configured() -> bool:
    # Gated on TASKS_REDIS_URL so the deciding process only opts a run into the dedicated
    # instance if it can itself reach it — a misconfigured pod fails safe to shared.
    return bool(settings.TASKS_REDIS_URL)


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


def get_tasks_stream_redis_sync(
    use_dedicated: bool = False,
    *,
    socket_timeout: float | None = None,
    socket_connect_timeout: float | None = None,
):
    return get_client(
        _tasks_stream_redis_url(use_dedicated),
        socket_timeout=socket_timeout,
        socket_connect_timeout=socket_connect_timeout,
    )


def get_tasks_cache() -> BaseCache:
    if settings.TASKS_REDIS_URL and TASKS_DEDICATED_CACHE_ALIAS in settings.CACHES:
        return caches[TASKS_DEDICATED_CACHE_ALIAS]
    return caches["default"]
