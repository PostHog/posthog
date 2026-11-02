"""The largest row group of each Parquet file a merge can rewrite, read from the file footers.

A deltalite reader reserves fetch budget for the largest compressed row group of a file, and then
holds one row group at a time. Delta add actions record the size of each file but not its row
groups, so the memory governor otherwise sizes each reader by the whole file. This module reads the
footers so that the governor can use the real row-group size.
"""

from __future__ import annotations

import logging
import threading
import urllib.parse
from collections import OrderedDict
from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor, wait

import pyarrow.fs as pafs
import pyarrow.parquet as pq
from deltalake.fs import DeltaStorageHandler

from posthog.dataclasses import frozen

logger = logging.getLogger(__name__)

#: Most footers one merge reads. Files past this keep their whole size as the bound.
_MAX_READS = 1024
#: Footers read at the same time. Each read is one ranged GET of the file tail.
_READ_CONCURRENCY = 32
#: Longest the footer reads of one merge may take. Files not read in time keep their whole size.
_READ_TIMEOUT_S = 10.0
#: Footer reads queued or running across all merges. A merge past this reads no footers.
_MAX_PENDING_READS = 2 * _MAX_READS
#: Files are immutable, so a footer read once stays correct. About 100 bytes per entry.
_CACHE_ENTRIES = 100_000


def largest_row_group_bytes(metadata: pq.FileMetaData) -> int:
    """Compressed bytes of the largest row group, counted as deltalite counts its fetch reservation."""
    largest = 0
    for i in range(metadata.num_row_groups):
        row_group = metadata.row_group(i)
        largest = max(largest, sum(row_group.column(c).total_compressed_size for c in range(row_group.num_columns)))
    return largest


class _ReadSlots:
    """Bounds the footer reads queued or running on the shared executor, over all merges."""

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._used = 0
        self._lock = threading.Lock()

    def acquire(self, wanted: int) -> int:
        with self._lock:
            granted = max(0, min(wanted, self._limit - self._used))
            self._used += granted
            return granted

    def release(self, count: int = 1) -> None:
        with self._lock:
            self._used -= count


def _read_footer(path: str, filesystem: pafs.FileSystem, expired: threading.Event, slots: _ReadSlots) -> int | None:
    # A read that its merge stopped waiting for still holds a slot until a worker takes it, so
    # stalled storage stops new reads instead of growing the queue.
    try:
        if expired.is_set():
            return None
        return largest_row_group_bytes(pq.read_metadata(path, filesystem=filesystem))
    finally:
        slots.release()


@frozen
class RowGroupSizes:
    """Largest row group per file path, for the files whose footer could be read."""

    bytes_by_path: Mapping[str, int]
    #: Footers fetched from storage for this call. Cache hits are not counted.
    footers_read: int = 0


class _FooterCache:
    """Process-wide LRU of the largest row group per (table, file)."""

    def __init__(self, max_entries: int) -> None:
        self._max_entries = max_entries
        self._entries: OrderedDict[tuple[str, str], int] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: tuple[str, str]) -> int | None:
        with self._lock:
            value = self._entries.get(key)
            if value is not None:
                self._entries.move_to_end(key)
            return value

    def put(self, key: tuple[str, str], value: int) -> None:
        with self._lock:
            self._entries[key] = value
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


_CACHE = _FooterCache(_CACHE_ENTRIES)

#: Shared by all merges, so reads that outlive their deadline cannot add threads past this bound.
_EXECUTOR = ThreadPoolExecutor(max_workers=_READ_CONCURRENCY, thread_name_prefix="row-group-footers")
_SLOTS = _ReadSlots(_MAX_PENDING_READS)

#: Opens a filesystem for a table that knows the sizes of the given files, so no read needs a HEAD.
OpenFilesystem = Callable[[Mapping[str, int]], pafs.FileSystem]


class RowGroupSizeReader:
    """Reads the largest row group of a table's files from their footers.

    A file whose footer cannot be read in time, or at all, is left out of the result, and the
    caller keeps its whole size as the bound. So a failure can only make the plan smaller.
    """

    def __init__(
        self,
        table_uri: str,
        storage_options: Mapping[str, str] | None = None,
        *,
        open_filesystem: OpenFilesystem | None = None,
        max_reads: int = _MAX_READS,
        executor: ThreadPoolExecutor = _EXECUTOR,
        slots: _ReadSlots = _SLOTS,
        timeout_s: float = _READ_TIMEOUT_S,
        cache: _FooterCache = _CACHE,
    ) -> None:
        self._table_uri = table_uri
        self._storage_options = dict(storage_options or {})
        self._open_filesystem = open_filesystem or self._delta_filesystem
        self._max_reads = max_reads
        self._executor = executor
        self._slots = slots
        self._timeout_s = timeout_s
        self._cache = cache

    def _delta_filesystem(self, known_sizes: Mapping[str, int]) -> pafs.FileSystem:
        handler = DeltaStorageHandler(self._table_uri, self._storage_options, dict(known_sizes))
        return pafs.PyFileSystem(handler)

    def largest_row_groups(self, sizes_by_path: Mapping[str, int]) -> RowGroupSizes:
        """The largest row group of each file in ``sizes_by_path``, largest files first."""
        found: dict[str, int] = {}
        to_read: dict[str, int] = {}
        for path, size in sorted(sizes_by_path.items(), key=lambda item: item[1], reverse=True):
            cached = self._cache.get((self._table_uri, path))
            if cached is not None:
                found[path] = cached
            elif len(to_read) < self._max_reads:
                to_read[path] = size
        granted = self._slots.acquire(len(to_read))
        to_read = dict(list(to_read.items())[:granted])
        if not to_read:
            return RowGroupSizes(bytes_by_path=found)

        # Add action paths are URI-encoded; the storage handler takes decoded paths.
        storage_paths = {path: urllib.parse.unquote(path) for path in to_read}
        expired = threading.Event()
        futures: dict[Future[int | None], str] = {}
        try:
            filesystem = self._open_filesystem({storage_paths[path]: size for path, size in to_read.items()})
            for path in to_read:
                future = self._executor.submit(_read_footer, storage_paths[path], filesystem, expired, self._slots)
                futures[future] = path
        except BaseException:
            # Each submitted read frees its own slot; the rest were never handed to a worker.
            self._slots.release(len(to_read) - len(futures))
            raise
        done, not_done = wait(futures, timeout=self._timeout_s)
        expired.set()

        failed = 0
        for future in done:
            path = futures[future]
            if future.exception() is not None:
                failed += 1
                continue
            result = future.result()
            if result is None:
                continue
            largest = min(result, to_read[path])
            self._cache.put((self._table_uri, path), largest)
            found[path] = largest
        if failed or not_done:
            logger.debug(
                "row group sizes: %d footer reads failed and %d timed out; those files keep their whole size",
                failed,
                len(not_done),
            )
        return RowGroupSizes(bytes_by_path=found, footers_read=len(done) - failed)
