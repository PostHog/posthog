import time
import threading
from typing import Any

from django.conf import settings
from django.core.cache import BaseCache, caches

import structlog
import posthoganalytics
import redis.exceptions
from django_redis.exceptions import ConnectionInterrupted

from posthog.caching.tasks_redis_cache import TASKS_DEDICATED_CACHE_ALIAS
from posthog.exceptions_capture import capture_exception
from posthog.redis import get_async_client, get_client

logger = structlog.get_logger(__name__)

# Redis/transport failures a best-effort cache call degrades on. django-redis wraps the raw
# redis error in ConnectionInterrupted; the raw redis errors and the builtin socket errors
# under OSError are caught too in case a backend surfaces them directly. Mirrors
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


# The best-effort helpers run on hot serialization paths, so capturing every failed redis
# command during an outage would emit hundreds of events per request. One capture per process
# per window is enough to surface the outage in error tracking; the warning log keeps the
# per-failure signal.
_CAPTURE_INTERVAL_SECONDS = 60.0
_capture_lock = threading.Lock()
_next_capture_at = 0.0


def _note_cache_failure(operation: str, error: Exception) -> None:
    global _next_capture_at
    logger.warning("tasks_cache_unavailable", operation=operation, error=type(error).__name__)
    now = time.monotonic()
    with _capture_lock:
        if now < _next_capture_at:
            return
        _next_capture_at = now + _CAPTURE_INTERVAL_SECONDS
    # The failing frame's locals hold the value being cached, and for the log URL cache that value
    # is a live presigned URL. Code-variable capture attaches those locals whatever properties the
    # call passes, so it is off here.
    with posthoganalytics.new_context():
        posthoganalytics.set_capture_exception_code_variables_context(False)
        capture_exception(error, additional_properties={"operation": operation})


# Per-process stand-in for the shared dedup/cooldown guards while redis is unavailable. A
# guard that fails open would let every callback through: each heartbeat opens a fresh
# Temporal connection in the request thread, and one turn end can push the same notification
# several times. Falling back per process bounds that at one pass per process per window.
# Same degrade shape as posthog/egress/limiter/backends.py.
_local_guard_lock = threading.Lock()
_local_guard_expiry: dict[str, float] = {}


def _drop_expired_guards(now: float) -> None:
    # Call with _local_guard_lock held.
    for key in [k for k, expires_at in _local_guard_expiry.items() if expires_at <= now]:
        del _local_guard_expiry[key]


def _local_guard_holds(key: str) -> bool:
    now = time.monotonic()
    with _local_guard_lock:
        _drop_expired_guards(now)
        return key in _local_guard_expiry


def _local_guard_add(key: str, timeout: int) -> bool:
    now = time.monotonic()
    with _local_guard_lock:
        _drop_expired_guards(now)
        if key in _local_guard_expiry:
            return False
        _local_guard_expiry[key] = now + timeout
        return True


def tasks_cache_get(key: str, default: Any = None) -> Any:
    """Best-effort ``cache.get``. Returns ``default`` on a redis failure instead of raising, so a
    redis blip cannot 500 a request that only reads an optional cached value."""
    try:
        return get_tasks_cache().get(key, default)
    except _REDIS_ERRORS as e:
        _note_cache_failure("get", e)
        return default


def tasks_cache_set(key: str, value: Any, timeout: int | None = None) -> bool:
    """Best-effort ``cache.set``. Returns whether the write landed; a redis failure degrades to
    ``False`` instead of raising."""
    try:
        get_tasks_cache().set(key, value, timeout=timeout)
        return True
    except _REDIS_ERRORS as e:
        _note_cache_failure("set", e)
        return False


def tasks_cache_add(key: str, value: Any, timeout: int) -> bool:
    """Best-effort ``cache.add`` used as a dedup/cooldown guard. Returns True when the key was
    newly added (the caller should proceed), False when it already existed. A redis failure
    degrades to a per-process guard with the same key and timeout, so an outage throttles per
    process instead of not at all."""
    # The guard is read before the redis write. Writing first and vetoing after would leave a
    # redis key that outlives the guard entry, so a recovery mid-window would suppress for up to
    # twice the timeout — long enough for the 60s heartbeat guard to starve a 120s inactivity
    # timer and end a live run.
    if _local_guard_holds(key):
        return False
    try:
        redis_added = bool(get_tasks_cache().add(key, value, timeout=timeout))
    except _REDIS_ERRORS as e:
        _note_cache_failure("add", e)
        return _local_guard_add(key, timeout)
    if redis_added:
        # Record the redis admission in the local guard too, so the fallback still suppresses a
        # repeat of this key if redis drops before the window ends.
        _local_guard_add(key, timeout)
    return redis_added
