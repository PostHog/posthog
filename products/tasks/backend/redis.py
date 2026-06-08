from django.conf import settings
from django.core.cache import BaseCache, caches

from posthog.caching.tasks_redis_cache import TASKS_DEDICATED_CACHE_ALIAS
from posthog.redis import get_async_client, get_client


def get_tasks_redis_url() -> str:
    return settings.TASKS_REDIS_URL or settings.REDIS_URL


def get_tasks_redis_async():
    return get_async_client(get_tasks_redis_url())


def get_tasks_redis_sync():
    return get_client(get_tasks_redis_url())


def get_tasks_cache() -> BaseCache:
    if settings.TASKS_REDIS_URL and TASKS_DEDICATED_CACHE_ALIAS in settings.CACHES:
        return caches[TASKS_DEDICATED_CACHE_ALIAS]
    return caches["default"]
