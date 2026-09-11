import json
import contextlib
from collections.abc import Iterator
from typing import Any

import redis
import structlog

from posthog.redis import get_client
from posthog.storage import object_storage

from products.tasks.backend.facade.contracts import TaskRunLogAppendUnserialized
from products.tasks.backend.metrics import LOG_APPEND_UNSERIALIZED_TOTAL

logger = structlog.get_logger(__name__)

# Must outlive the whole-object read + write below.
_APPEND_LOCK_TTL_SECONDS = 3 * 60
_APPEND_LOCK_WAIT_SECONDS = 5


@contextlib.contextmanager
def _append_lock(object_storage_key: str, attempts: int) -> Iterator[None]:
    """Serialize the read-modify-write below.

    Contention past the attempts is refused so a concurrent batch is never overwritten;
    callers without their own retry loop ask for more attempts. Redis being unavailable
    proceeds unserialized instead, since refusing every append for the whole outage would
    lose far more than the rare overlapping pair.
    """
    try:
        lock = get_client().lock(
            f"tasks:log_append:{object_storage_key}",
            timeout=_APPEND_LOCK_TTL_SECONDS,
            blocking_timeout=_APPEND_LOCK_WAIT_SECONDS,
        )
        acquired = any(lock.acquire() for _ in range(attempts))
    except redis.exceptions.RedisError:
        logger.warning("task_log_append_lock_unavailable", object_storage_key=object_storage_key, exc_info=True)
        LOG_APPEND_UNSERIALIZED_TOTAL.labels(reason="redis_unavailable").inc()
        yield
        return

    if not acquired:
        LOG_APPEND_UNSERIALIZED_TOTAL.labels(reason="contended").inc()
        raise TaskRunLogAppendUnserialized()

    try:
        yield
    finally:
        try:
            lock.release()
        except redis.exceptions.LockNotOwnedError:
            logger.warning("task_log_append_lock_expired", object_storage_key=object_storage_key)
        except redis.exceptions.RedisError:
            logger.warning("task_log_append_lock_release_failed", object_storage_key=object_storage_key, exc_info=True)


def append_jsonl_object(object_storage_key: str, entries: list[dict[str, Any]], *, lock_attempts: int = 1) -> bool:
    with _append_lock(object_storage_key, lock_attempts):
        existing_content = object_storage.read(object_storage_key, missing_ok=True) or ""
        is_new_object = not existing_content
        new_lines = "\n".join(json.dumps(entry) for entry in entries)
        content = existing_content + ("\n" if existing_content else "") + new_lines

        object_storage.write(object_storage_key, content)

        return is_new_object
