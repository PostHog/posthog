import json
import contextlib
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import redis
import structlog

from posthog.redis import get_client
from posthog.storage import object_storage

from products.tasks.backend.metrics import LOG_APPEND_UNSERIALIZED_TOTAL
from products.tasks.backend.storage_errors import TaskRunLogAppendUnserialized

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


def _json_lines(entries: list[dict[str, Any]]) -> str:
    return "\n".join(json.dumps(entry) for entry in entries)


def append_jsonl_object(
    object_storage_key: str, entries: list[dict[str, Any]], *, lock_attempts: int = 1, batch_id: str | None = None
) -> bool:
    """Append ``entries`` as JSON lines. Returns whether the object was created by this call.

    ``batch_id`` makes the append idempotent: every entry is written with ``"batch": batch_id``,
    and the append is skipped when the object already holds that batch. A caller that appended,
    then failed before recording it, can retry without writing the lines twice.
    """
    with _append_lock(object_storage_key, lock_attempts):
        if batch_id is None:
            return object_storage.append(object_storage_key, _json_lines(entries).encode(), separator=b"\n")
        existing_content = object_storage.read(object_storage_key, missing_ok=True) or ""
        if f'"batch": {json.dumps(batch_id)}' in existing_content:
            return False
        batch_lines = _json_lines([{**entry, "batch": batch_id} for entry in entries])
        content = existing_content + ("\n" if existing_content else "") + batch_lines

        object_storage.write(object_storage_key, content)

        return not existing_content


@dataclass(frozen=True, slots=True)
class TaskRunLog:
    key: str


def read_run_log(log: TaskRunLog) -> str:
    return object_storage.read(log.key, missing_ok=True) or ""


def read_run_log_tail(log: TaskRunLog, max_bytes: int) -> str:
    """The last whole JSONL lines that fit in `max_bytes`. A cut first line is dropped."""
    content = object_storage.read_bytes_tail(log.key, max_bytes) or b""
    if len(content) >= max_bytes:
        content = content.split(b"\n", 1)[1] if b"\n" in content else b""
    return content.decode("utf-8", errors="replace")


def read_run_log_bytes(log: TaskRunLog) -> bytes:
    return object_storage.read_bytes(log.key, missing_ok=True) or b""


def read_run_log_size(log: TaskRunLog, *, strict: bool) -> int:
    if strict:
        head = object_storage.head_object_strict(log.key)
    else:
        head = object_storage.head_object(log.key)
    if not head:
        return 0
    return int(head.get("ContentLength") or 0)


def copy_run_log(log: TaskRunLog, target_key: str) -> None:
    object_storage.copy(log.key, target_key)
