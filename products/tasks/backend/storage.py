import json
import uuid
import contextlib
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

import redis
import structlog

from posthog.redis import get_client
from posthog.storage import object_storage
from posthog.storage.object_storage import ObjectStorageError, StoredObjectSummary

from products.tasks.backend.metrics import LOG_APPEND_UNSERIALIZED_TOTAL
from products.tasks.backend.storage_errors import (
    TaskRunLogAppendUnserialized,
    TaskRunLogChunkMissing,
    TaskRunLogChunkSlotsTaken,
)

logger = structlog.get_logger(__name__)

# Must outlive the whole-object read + write below.
_APPEND_LOCK_TTL_SECONDS = 3 * 60
_APPEND_LOCK_WAIT_SECONDS = 5

# Parallel chunk requests per read; matches boto3's default pool of 10 connections.
CHUNK_READ_CONCURRENCY = 10
# Ceiling on chunks per run, so probing for the end of a log always stops.
CHUNK_COUNT_MAX = 1_000_000
# Taken slots an append retries past before it gives up.
CHUNK_WRITE_ATTEMPTS_MAX = 8
_APPEND_ID_METADATA_KEY = "append-id"
FOLD_FANOUT = 64
FOLD_LEVEL_MAX = 3
FOLD_BYTES_MAX = 8 * 1024 * 1024
_SEALED_LEVEL = FOLD_LEVEL_MAX + 1

assert FOLD_FANOUT**FOLD_LEVEL_MAX <= CHUNK_COUNT_MAX < FOLD_FANOUT ** (FOLD_LEVEL_MAX + 1)

T = TypeVar("T")


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


def _batch_marker(batch_id: str) -> str:
    return f'"batch": {json.dumps(batch_id)}'


def _with_batch(entries: list[dict[str, Any]], batch_id: str | None) -> list[dict[str, Any]]:
    if batch_id is None:
        return entries
    return [{**entry, "batch": batch_id} for entry in entries]


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
        if _batch_marker(batch_id) in existing_content:
            return False
        batch_lines = _json_lines(_with_batch(entries, batch_id))
        content = existing_content + ("\n" if existing_content else "") + batch_lines

        object_storage.write(object_storage_key, content)

        return not existing_content


@dataclass(frozen=True, slots=True)
class TaskRunLog:
    key: str
    chunked: bool = False
    chunk_count: int = field(default=0, compare=False)
    finished: bool = field(default=False, compare=False)


@dataclass(frozen=True, slots=True)
class _LogUnit:
    level: int
    first: int
    stop: int


@dataclass(frozen=True, slots=True)
class _LogParts(Generic[T]):
    parts: list[T]
    tail: list[T]
    end: int
    sealed: bool


def _log_prefix(log: TaskRunLog) -> str:
    assert log.key.endswith(".jsonl"), log.key
    return f"{log.key.removesuffix('.jsonl')}/"


def _chunk_prefix(log: TaskRunLog) -> str:
    return f"{_log_prefix(log)}chunks/"


def run_log_chunk_key(log: TaskRunLog, chunk_index: int) -> str:
    assert 0 <= chunk_index < CHUNK_COUNT_MAX, chunk_index
    return f"{_chunk_prefix(log)}{chunk_index:010d}.jsonl"


def _unit_key(log: TaskRunLog, unit: _LogUnit) -> str:
    if unit.level == 0:
        return run_log_chunk_key(log, unit.first)
    if unit.level == _SEALED_LEVEL:
        assert unit.first == 0, unit
        return f"{_log_prefix(log)}sealed/{unit.stop:010d}.jsonl"
    assert 0 < unit.level <= FOLD_LEVEL_MAX, unit
    return f"{_log_prefix(log)}folds/{unit.level}/{unit.first:010d}.jsonl"


def _fold_units(start: int, stop: int, level_max: int) -> list[_LogUnit]:
    assert 0 <= start <= stop <= CHUNK_COUNT_MAX, (start, stop)
    assert 0 <= level_max <= FOLD_LEVEL_MAX, level_max
    units: list[_LogUnit] = []
    position = start
    while position < stop:
        level = level_max
        while level > 0 and (position % FOLD_FANOUT**level != 0 or position + FOLD_FANOUT**level > stop):
            level -= 1
        units.append(_LogUnit(level=level, first=position, stop=position + FOLD_FANOUT**level))
        position += FOLD_FANOUT**level
    assert position == stop, (position, stop)
    return units


def _unit_parts(unit: _LogUnit) -> list[_LogUnit]:
    assert unit.level > 0, unit
    return _fold_units(unit.first, unit.stop, min(unit.level - 1, FOLD_LEVEL_MAX))


def _log_plan(log: TaskRunLog, start: int, stop: int) -> list[_LogUnit]:
    if log.finished and start == 0 and stop > 0:
        return [_LogUnit(level=_SEALED_LEVEL, first=0, stop=stop)]
    return _fold_units(start, stop, FOLD_LEVEL_MAX)


def _list_chunks(log: TaskRunLog) -> list[StoredObjectSummary]:
    chunks: list[StoredObjectSummary] = []
    for summary in object_storage.list_object_summaries(_chunk_prefix(log)):
        if summary.key != run_log_chunk_key(log, len(chunks)):
            break
        chunks.append(summary)
    return chunks


def _fetch_keys(fetch: Callable[[str], T | None], keys: list[str]) -> list[T | None]:
    if len(keys) <= 1:
        return [fetch(key) for key in keys]
    with ThreadPoolExecutor(max_workers=min(CHUNK_READ_CONCURRENCY, len(keys))) as pool:
        return list(pool.map(fetch, keys, buffersize=CHUNK_READ_CONCURRENCY))


def _fetch_chunks_from(log: TaskRunLog, fetch: Callable[[str], T | None], start: int) -> list[T]:
    found: list[T] = []
    wave = 1
    while start < CHUNK_COUNT_MAX:
        stop = min(start + wave, CHUNK_COUNT_MAX)
        for item in _fetch_keys(fetch, [run_log_chunk_key(log, chunk_index) for chunk_index in range(start, stop)]):
            if item is None:
                return found
            found.append(item)
        start = stop
        wave = min(wave * 2, CHUNK_READ_CONCURRENCY)
    raise TaskRunLogChunkMissing(f"{log.key} has no end below {CHUNK_COUNT_MAX} chunks")


def _settle_units(
    log: TaskRunLog, fetch: Callable[[str], T | None], pending: list[_LogUnit], fetched: list[T | None]
) -> list[T]:
    found: dict[int, T] = {}
    for _ in range(_SEALED_LEVEL + 1):
        missing: list[_LogUnit] = []
        for unit, item in zip(pending, fetched, strict=True):
            if item is not None:
                found[unit.first] = item
            elif unit.level == 0:
                raise TaskRunLogChunkMissing(f"{_unit_key(log, unit)} is missing below chunk count {log.chunk_count}")
            else:
                missing.extend(_unit_parts(unit))
        if not missing:
            return [found[first] for first in sorted(found)]
        pending = missing
        fetched = _fetch_keys(fetch, [_unit_key(log, unit) for unit in pending])
    raise AssertionError(f"{log.key} fell back below single chunks")


def _fetch_log(log: TaskRunLog, fetch: Callable[[str], T | None], start: int) -> _LogParts[T]:
    assert log.chunked
    assert 0 <= log.chunk_count < CHUNK_COUNT_MAX, log.chunk_count
    assert 0 <= start < CHUNK_COUNT_MAX, start
    stop = max(start, log.chunk_count)
    pending = _log_plan(log, start, stop)
    fetched = _fetch_keys(fetch, [_unit_key(log, unit) for unit in pending] + [run_log_chunk_key(log, stop)])
    sealed = bool(pending) and pending[0].level == _SEALED_LEVEL and fetched[0] is not None
    parts = _settle_units(log, fetch, pending, fetched[:-1])
    if fetched[-1] is None:
        return _LogParts(parts=parts, tail=[], end=stop, sealed=sealed)
    tail = [fetched[-1], *_fetch_chunks_from(log, fetch, stop + 1)]
    return _LogParts(parts=parts, tail=tail, end=stop + len(tail), sealed=sealed)


def _read_missing_ok(key: str) -> bytes | None:
    return object_storage.read_bytes(key, missing_ok=True)


def _content_length(key: str) -> int | None:
    head = object_storage.head_object_strict(key)
    if head is None:
        return None
    return int(head.get("ContentLength") or 0)


def _write_seal(log: TaskRunLog, body: bytes) -> None:
    assert log.finished
    assert log.chunk_count > 0, log.chunk_count
    seal = _LogUnit(level=_SEALED_LEVEL, first=0, stop=log.chunk_count)
    try:
        object_storage.write_if_absent(_unit_key(log, seal), body, metadata={})
    except ObjectStorageError:
        logger.warning("task_run_log_seal_failed", object_storage_key=log.key, exc_info=True)


class RunLogCache:
    __slots__ = ("_snapshot",)

    def __init__(self) -> None:
        self._snapshot: tuple[int, bytes] = (0, b"")

    def read(self, log: TaskRunLog) -> str:
        if not log.chunked:
            return read_run_log(log)
        chunk_count, content = self._snapshot
        fetched = _fetch_log(log, _read_missing_ok, chunk_count)
        snapshot = (fetched.end, content + b"".join(fetched.parts) + b"".join(fetched.tail))
        self._snapshot = snapshot
        return snapshot[1].decode("utf-8")


def read_run_log(log: TaskRunLog) -> str:
    if log.chunked:
        return read_run_log_bytes(log).decode("utf-8")
    return object_storage.read(log.key, missing_ok=True) or ""


def read_run_log_bytes(log: TaskRunLog) -> bytes:
    if log.chunked:
        fetched = _fetch_log(log, _read_missing_ok, 0)
        body = b"".join(fetched.parts)
        if log.finished and log.chunk_count > 0 and not fetched.sealed:
            _write_seal(log, body)
        return body + b"".join(fetched.tail)
    return object_storage.read_bytes(log.key, missing_ok=True) or b""


def read_run_log_size(log: TaskRunLog, *, strict: bool) -> int:
    if log.chunked:
        try:
            fetched = _fetch_log(log, _content_length, 0)
        except ObjectStorageError:
            if strict:
                raise
            return 0
        return sum(fetched.parts) + sum(fetched.tail)
    if strict:
        head = object_storage.head_object_strict(log.key)
    else:
        head = object_storage.head_object(log.key)
    if not head:
        return 0
    return int(head.get("ContentLength") or 0)


def read_run_log_version(log: TaskRunLog) -> str | None:
    if log.chunked:
        try:
            tail = _fetch_chunks_from(log, object_storage.head_object_strict, log.chunk_count)
        except ObjectStorageError:
            return None
        chunk_count = log.chunk_count + len(tail)
        return f"chunks-{chunk_count}" if chunk_count else None
    size = read_run_log_size(log, strict=False)
    return str(size) if size else None


def run_log_exists(log: TaskRunLog) -> bool:
    assert not log.chunked
    return object_storage.head_object(log.key) is not None


def copy_run_log(log: TaskRunLog, target_key: str) -> None:
    if log.chunked:
        object_storage.write(target_key, read_run_log_bytes(log))
        return
    object_storage.copy(log.key, target_key)


def run_log_download_url(
    log: TaskRunLog, *, expiration_seconds: int, content_disposition: str | None = None
) -> str | None:
    assert not log.chunked
    return object_storage.get_presigned_url(
        log.key, expiration=expiration_seconds, content_disposition=content_disposition
    )


def _chunk_append_id(chunk_key: str) -> str | None:
    head = object_storage.head_object_strict(chunk_key)
    if head is None:
        return None
    return head.get("Metadata", {}).get(_APPEND_ID_METADATA_KEY)


def _write_chunk(log: TaskRunLog, body: bytes, metadata: dict[str, str]) -> int:
    chunk_index = log.chunk_count
    for _ in range(CHUNK_WRITE_ATTEMPTS_MAX):
        chunk_key = run_log_chunk_key(log, chunk_index)
        if object_storage.write_if_absent(chunk_key, body, metadata=metadata):
            return chunk_index + 1
        if _chunk_append_id(chunk_key) == metadata[_APPEND_ID_METADATA_KEY]:
            return chunk_index + 1
        chunk_index = len(_list_chunks(log))
    raise TaskRunLogChunkSlotsTaken(f"{log.key} lost {CHUNK_WRITE_ATTEMPTS_MAX} races for a free chunk")


def _write_fold(log: TaskRunLog, fold: _LogUnit) -> None:
    assert 0 < fold.level <= FOLD_LEVEL_MAX, fold
    keys = (_unit_key(log, part) for part in _unit_parts(fold))
    parts: list[bytes] = []
    size = 0
    with ThreadPoolExecutor(max_workers=CHUNK_READ_CONCURRENCY) as pool:
        for part in pool.map(_read_missing_ok, keys, buffersize=CHUNK_READ_CONCURRENCY):
            if part is None:
                return
            size += len(part)
            if size > FOLD_BYTES_MAX:
                return
            parts.append(part)
    object_storage.write_if_absent(_unit_key(log, fold), b"".join(parts), metadata={})


def _fold_full_blocks(log: TaskRunLog, chunk_count: int) -> None:
    assert 0 < chunk_count <= CHUNK_COUNT_MAX, chunk_count
    for level in range(1, FOLD_LEVEL_MAX + 1):
        if chunk_count % FOLD_FANOUT**level != 0:
            return
        _write_fold(log, _LogUnit(level=level, first=chunk_count - FOLD_FANOUT**level, stop=chunk_count))


def append_run_log_chunk(
    log: TaskRunLog, entries: list[dict[str, Any]], *, lock_attempts: int, batch_id: str | None
) -> int | None:
    assert log.chunked
    assert entries
    body = (_json_lines(_with_batch(entries, batch_id)) + "\n").encode()
    metadata = {_APPEND_ID_METADATA_KEY: uuid.uuid4().hex}
    with _append_lock(log.key, lock_attempts):
        if batch_id is not None and _batch_marker(batch_id) in read_run_log(log):
            return None
        chunk_count = _write_chunk(log, body, metadata)
    try:
        _fold_full_blocks(log, chunk_count)
    except (ObjectStorageError, TaskRunLogChunkMissing):
        logger.warning("task_run_log_fold_failed", object_storage_key=log.key, chunk_count=chunk_count, exc_info=True)
    return chunk_count
