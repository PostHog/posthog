"""A process-wide cache of open deltalite table handles.

Opening a `DeltaLiteTable` is a full snapshot load: a checkpoint read plus every commit since, all
over object storage. The handle then refreshes itself incrementally before each upsert, so a
loader that keeps one handle per table pays the full load once and one log listing per batch.

A cached handle is only reused for the table it was opened on. A reset or a repartition swap
replaces the table under the same URI with a new one (a new table id, a lower version), and a
handle that applied fresh commits on top of the old snapshot would plan a write against files
that no longer exist. The caller therefore hands in the identity of the table it has just opened
through delta-rs, and a handle that disagrees with it is thrown away.
"""

from __future__ import annotations

import time
import threading
import contextlib
from collections import OrderedDict
from collections.abc import Callable, Iterator
from typing import Any

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.memory_governor import get_governor

# A table nobody wrote to for this long gives its snapshot memory back. Sized above the gap
# between two syncs of a frequently scheduled schema, so those keep their handle.
HANDLE_IDLE_SECONDS = 600.0

Opener = Callable[[str, dict[str, str]], Any]


def _open_deltalite_table(uri: str, storage_options: dict[str, str]) -> Any:
    # Imported at call time so a process that never writes through deltalite never loads it.
    import deltalite  # noqa: PLC0415

    return deltalite.DeltaLiteTable.open(uri, storage_options)


@frozen(frozen=False)
class _Entry:
    handle: Any
    table_id: str
    # The version the handle observed after its last upsert, recorded under the entry lock. Read
    # instead of `handle.version()` because a pyo3 object refuses a second borrow while another
    # thread's upsert holds it mutably.
    version: int
    storage_options: dict[str, str]
    last_used: float
    lock: threading.Lock


class DeltaLiteHandleCache:
    """LRU of open deltalite handles keyed by table URI, safe to share across worker threads."""

    def __init__(
        self,
        *,
        maxsize: int,
        idle_seconds: float = HANDLE_IDLE_SECONDS,
        opener: Opener = _open_deltalite_table,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._maxsize = max(1, maxsize)
        self._idle_seconds = idle_seconds
        self._opener = opener
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: OrderedDict[str, _Entry] = OrderedDict()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def __contains__(self, uri: object) -> bool:
        with self._lock:
            return uri in self._entries

    @contextlib.contextmanager
    def lease(self, uri: str, *, storage_options: dict[str, str], table_id: str, table_version: int) -> Iterator[Any]:
        """Yield the handle for `uri` for exclusive use, opening or replacing it as needed.

        `table_id` and `table_version` describe the table as the caller has just read it from the
        live log. A cached handle that was opened on another table, with other credentials, or
        that is ahead of the live log is replaced.
        """
        entry = self._get_or_open(uri, storage_options, table_id, table_version)
        with entry.lock:
            try:
                yield entry.handle
            except Exception:
                # The handle's snapshot may be the reason it failed; the next batch reopens.
                self._drop(uri, entry)
                raise
            entry.version = self._observed_version(entry.handle, table_version)
            entry.last_used = self._clock()

    def invalidate(self, uri: str) -> None:
        with self._lock:
            self._entries.pop(uri, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def _get_or_open(self, uri: str, storage_options: dict[str, str], table_id: str, table_version: int) -> _Entry:
        now = self._clock()
        with self._lock:
            self._evict_idle(now)
            entry = self._entries.get(uri)
            if entry is not None and not self._reusable(entry, storage_options, table_id, table_version):
                del self._entries[uri]
                entry = None
            if entry is not None:
                self._entries.move_to_end(uri)
                entry.last_used = now
                return entry

        # Opening is object-storage I/O, so it runs outside the cache lock.
        handle = self._opener(uri, dict(storage_options))
        opened = _Entry(
            handle=handle,
            table_id=table_id,
            version=self._observed_version(handle, table_version),
            storage_options=dict(storage_options),
            last_used=now,
            lock=threading.Lock(),
        )
        with self._lock:
            racing = self._entries.get(uri)
            if racing is not None and self._reusable(racing, storage_options, table_id, table_version):
                return racing
            self._entries[uri] = opened
            self._entries.move_to_end(uri)
            while len(self._entries) > self._maxsize:
                self._entries.popitem(last=False)
        return opened

    def _drop(self, uri: str, entry: _Entry) -> None:
        with self._lock:
            if self._entries.get(uri) is entry:
                del self._entries[uri]

    def _evict_idle(self, now: float) -> None:
        for uri, entry in list(self._entries.items()):
            if now - entry.last_used > self._idle_seconds:
                del self._entries[uri]

    @staticmethod
    def _reusable(entry: _Entry, storage_options: dict[str, str], table_id: str, table_version: int) -> bool:
        return (
            entry.table_id == table_id and entry.storage_options == storage_options and entry.version <= table_version
        )

    @staticmethod
    def _observed_version(handle: Any, fallback: int) -> int:
        try:
            version = handle.version()
        except Exception:  # noqa: BLE001 - a handle that cannot report its version is treated as current
            return fallback
        return version if isinstance(version, int) else fallback


_CACHE: DeltaLiteHandleCache | None = None
_CACHE_LOCK = threading.Lock()


def get_handle_cache() -> DeltaLiteHandleCache:
    """The process-wide cache, sized to the number of upserts this process runs at once."""
    global _CACHE
    if _CACHE is None:
        with _CACHE_LOCK:
            if _CACHE is None:
                _CACHE = DeltaLiteHandleCache(maxsize=get_governor().config.max_concurrent)
    return _CACHE
