from datetime import UTC, datetime

from django.conf import settings
from django.core.cache import BaseCache, caches

from posthog.caching.tasks_redis_cache import TASKS_DEDICATED_CACHE_ALIAS
from posthog.redis import get_async_client, get_client

# One-time stream cutover: runs created on/after this instant use the dedicated tasks Redis;
# older runs stay on the shared Redis until their streams drain (~6h TTL), so a live run is
# never split across instances. Transitional — remove this and the stream routing below once
# prod-us has fully drained past the cutover.
TASKS_REDIS_STREAM_CUTOVER_AT = datetime(2026, 6, 9, 0, 0, tzinfo=UTC)


def _use_dedicated_stream(created_at: datetime | None) -> bool:
    if not settings.TASKS_REDIS_URL:
        return False
    if created_at is None:
        # Unknown creation time: stay on the shared Redis so we never split an
        # already-running pre-cutover stream across instances.
        return False
    return created_at >= TASKS_REDIS_STREAM_CUTOVER_AT


def _tasks_stream_redis_url(created_at: datetime | None) -> str:
    dedicated = settings.TASKS_REDIS_URL
    if dedicated is not None and _use_dedicated_stream(created_at):
        return dedicated
    return settings.REDIS_URL


def get_tasks_stream_redis_async(created_at: datetime | None = None):
    return get_async_client(_tasks_stream_redis_url(created_at))


def get_tasks_stream_redis_sync(created_at: datetime | None = None):
    return get_client(_tasks_stream_redis_url(created_at))


def get_tasks_cache() -> BaseCache:
    if settings.TASKS_REDIS_URL and TASKS_DEDICATED_CACHE_ALIAS in settings.CACHES:
        return caches[TASKS_DEDICATED_CACHE_ALIAS]
    return caches["default"]
