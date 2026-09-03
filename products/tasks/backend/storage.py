import json
import contextlib
from collections.abc import Iterator
from typing import Any

import redis
import structlog

from posthog.redis import get_client
from posthog.storage import object_storage

from products.tasks.backend.metrics import LOG_APPEND_UNSERIALIZED_TOTAL

logger = structlog.get_logger(__name__)

# Must outlive read + write, each bounded by botocore's 60s default read_timeout.
_APPEND_LOCK_TTL_SECONDS = 3 * 60
_APPEND_LOCK_WAIT_SECONDS = 15


@contextlib.contextmanager
def _append_lock(object_storage_key: str) -> Iterator[None]:
    """Serialize the read-modify-write below; fails open so redis can't break the agent's flush."""
    lock = None
    acquired = False

    try:
        lock = get_client().lock(
            f"tasks:log_append:{object_storage_key}",
            timeout=_APPEND_LOCK_TTL_SECONDS,
            blocking_timeout=_APPEND_LOCK_WAIT_SECONDS,
        )
        acquired = bool(lock.acquire())
    except redis.exceptions.RedisError:
        logger.warning("task_log_append_lock_unavailable", object_storage_key=object_storage_key, exc_info=True)

    if not acquired:
        LOG_APPEND_UNSERIALIZED_TOTAL.inc()

    try:
        yield
    finally:
        if acquired and lock is not None:
            try:
                lock.release()
            except redis.exceptions.RedisError:
                logger.warning(
                    "task_log_append_lock_release_failed", object_storage_key=object_storage_key, exc_info=True
                )


def append_jsonl_object(object_storage_key: str, entries: list[dict[str, Any]]) -> bool:
    with _append_lock(object_storage_key):
        existing_content = object_storage.read(object_storage_key, missing_ok=True) or ""
        is_new_object = not existing_content
        new_lines = "\n".join(json.dumps(entry) for entry in entries)
        content = existing_content + ("\n" if existing_content else "") + new_lines

        object_storage.write(object_storage_key, content)

        return is_new_object
