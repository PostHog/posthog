"""Runtime memory capacity planning for concurrent deltalite upserts on one pod.

deltalite runs as Temporal activity threads inside a single worker process: every
concurrent upsert — plus every delta-rs MERGE fallback and full-sync ``write_deltalake`` —
shares one address space and one cgroup memory limit. This governor decides, per upsert and
how large an upsert to run: it picks the per-call knobs
(``max_parallel_partitions`` / ``max_parallel_files`` / ``max_buffered_bytes`` /
``probe_concurrency``) sized to a fixed
per-upsert slice of pod memory. The slice is ``(pod limit × safety − reserve) / max_concurrent``,
so however many upserts run at once (up to the pod's ``MAX_CONCURRENT_ACTIVITIES``) their peaks sum
to less than the pod. deltalite therefore **always writes** — it never falls back to the delta-rs
MERGE for capacity, because the MERGE is the *more* memory-hungry path and falling back to it under
pressure is exactly what would OOM the pod. A source too big for its slice runs at the smallest
plan (the memory floor, still far below the MERGE) and raises an ops signal, rather than falling back.

Two layers, by design:

* This governor (Python) is the **planner**. It divides the usable pod memory into equal
  per-upsert slices (one per concurrent activity) and sizes each upsert's knobs to its slice, so
  the concurrent upserts always fit. Memory for *non-deltalite* writers (full syncs, the rare
  genuine-error MERGE fallback whose RSS tracks table size, interpreter and allocator slack) is
  held back up front as ``reserve_mb``. It also samples the process RSS while each upsert runs,
  so the logs carry the real peak next to the prediction.
* ``deltalite_core::limits`` (the ``DELTALITE_PROCESS_*`` env ceilings) is the **hard backstop**
  in Rust: process-global semaphores that cap total in-flight work regardless of what the
  governor predicted. The governor aims never to reach it; the backstop guarantees safety when a
  prediction is wrong.

The memory model follows the shape of the files a merge rewrites, not their total size. A
partition worker in deltalite 0.1.9 holds three things at its peak:

* **Readers.** Each of its ``max_parallel_files`` readers fetches one whole compressed row group
  before it decodes it, and no budget covers that fetch. A worker therefore holds about the sum of
  its largest ``max_parallel_files`` candidate row groups.
* **Writer.** The write buffer grows to ``target_file_size`` before it flushes, and the flush
  copies it once more. A partition that writes less than the target only buffers what it writes.
* **Decode.** Decoded survivor batches in flight, capped per call by ``max_buffered_bytes``.

Profiling on Linux showed that peak memory does not grow with the partition count, the file count
or the total bytes a merge rewrites — only with these per-worker terms. The terms are named
constants, so a deltalite release that budgets the fetch or streams the write changes one number.
"""

from __future__ import annotations

import os
import time
import heapq
import asyncio
import logging
import threading
import contextlib
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from django.conf import settings

import pyarrow as pa
import pyarrow.compute as pc

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.rss_sampler import (
    RssPeakSampler,
    RssWindow,
    psutil_rss_mb,
)

if TYPE_CHECKING:
    import deltalake

logger = logging.getLogger(__name__)

MB = 1024 * 1024

Mode = Literal["off", "advisory", "enforce"]

#: Fallback concurrency when nothing else declares it. The Temporal SDK's own default is 100
#: (posthog's worker wrapper uses 50); we pick the higher value so an unknown concurrency yields a
#: smaller, safer per-upsert slice rather than over-commit.
_DEFAULT_MAX_CONCURRENT = 100

#: A process's real max concurrent upserts, declared at startup via ``configure_process_concurrency``
#: (e.g. the v3 loader passes its BatchConsumer ``max_concurrency``). Set here rather than read from
#: an env var so the governor uses the loader's actual source of truth. None until declared.
_PROCESS_MAX_CONCURRENT: int | None = None

# --- File-shape memory model (deltalite 0.1.9) -------------------------------------------------
#
# Fitted on a Linux harness that runs the loader's exact upsert (glibc, 30-column tables): small
# files over 100 to 1,000 partitions, single partitions of 57 MB and 99 MiB single-row-group files,
# and four partitions of 57 MB files, with max_parallel_files 1, 2 and 4 and target_file_size 32
# and 100 MiB. The model predicts malloc in-use bytes; ``_rss_retention`` turns that into RSS,
# which is what the cgroup limit counts.

#: Resident bytes per stored byte of the row group one reader fetches. deltalite 0.1.9 fetches the
#: whole compressed row group before it decodes it, outside every budget. Lower this when deltalite
#: budgets or streams the fetch.
_READER_BYTES_PER_ROW_GROUP_BYTE = 1.0
#: Each reader also holds decompressed pages next to the fetched row group: ~22 MB per reader on
#: 57 MB and 99 MiB row groups of the 30-column harness tables, far less on small row groups.
_READER_PAGE_BUFFER_MB = 22.0
#: Cap on the page buffers as a share of the row group, which keeps small row groups small.
_READER_PAGE_BUFFER_SHARE = 0.4
#: Resident bytes per byte of ``target_file_size`` in one partition worker's writer: the buffer
#: grows to the target before it flushes, and the flush copies it. Lower this when deltalite
#: streams the write.
_WRITER_BYTES_PER_TARGET_BYTE = 2.3
#: Part of ``max_buffered_bytes`` that decoded batches actually fill at the peak.
_DECODE_BUDGET_FILL = 0.875
#: Decoded bytes per stored byte, used only to cap the decode term for small files.
_DECODED_BYTES_PER_STORED_BYTE = 1.5
#: Per upsert, before any partition worker: channels, tasks, the commit.
_BASE_INUSE_MB = 6.0
#: Per candidate file, the plan state deltalite keeps for it (its add action, the remove it may
#: write). Fitted on 600 to 6,000 candidate files.
_PLAN_KB_PER_CANDIDATE_FILE = 2.6
#: Per upsert, per MB of its source batch (the cast copy and the PK sets). Kept from the earlier
#: threaded benchmark: the harness sources were too small to fit it again.
_SOURCE_INUSE_PER_MB = 0.73
#: deltalite keeps one add action per table file in its snapshot. Measured at ~2.2 KB per file on
#: the 30-column harness tables (6,000 files hold 12 MB more than 600 files).
_SNAPSHOT_KB_PER_FILE = 2.2
#: deltalite and delta-rs both default to 100 MiB when the table does not set ``delta.targetFileSize``.
_DEFAULT_TARGET_FILE_SIZE = 100 * MB

#: RSS per byte of malloc in-use memory. glibc keeps freed memory in its arenas, and with its
#: default mmap threshold the large Arrow buffers stay there too. RSS ran 1.25–2.1× in-use in most
#: cases and 4.8× in one, so this is a middle value, not a bound.
_RSS_RETENTION_GLIBC_DEFAULT = 2.0
#: With ``MALLOC_MMAP_THRESHOLD_`` at 128 KiB, large buffers go back to the kernel on free: RSS ran
#: 1.2–1.4× in-use.
_RSS_RETENTION_LOW_MMAP_THRESHOLD = 1.4
#: Highest ``MALLOC_MMAP_THRESHOLD_`` that earns the lower retention. 1 MiB still retained 1.6×.
_LOW_MMAP_THRESHOLD_BYTES = 256 * 1024

#: Beyond 4 partition workers the measured wall-clock gains vanish while memory keeps climbing.
_MAX_PARALLEL_PARTITIONS = 4
#: Concurrent file readers inside one partition worker at deltalite's own default.
_DEFAULT_FILES_PER_WORKER = 4
#: Most readers one partition worker may run. A partition with few, small row groups gains I/O
#: overlap from more; the reader term charges every extra reader its row group.
_MAX_PARALLEL_FILES = 8
#: Ceiling on ``max_parallel_partitions × max_parallel_files`` for one upsert, the process-wide
#: reader limit deltalite enforces by default.
_MAX_READERS_PER_UPSERT = 16
#: Concurrent PK-column probes per partition worker. Each probe holds a Parquet footer and one
#: decoded batch of the PK columns, and that batch takes byte-budget permits like a rewrite batch,
#: so probe memory is capped by ``max_buffered_bytes`` at any concurrency. Insert-only batches
#: into tables with many files are bound by probe round trips, and this overlaps them.
_PROBE_CONCURRENCY = 32
#: deltalite's default, kept explicit so the write is deterministic. The per-call cap on decoded
#: bytes in flight; the reader and probe knobs above scale latency overlap, not this.
_DEFAULT_BUFFERED_BYTES = 64 * MB
#: How often a waiting admission checks for room.
_WAIT_POLL_S = 0.5
#: Rounding slack on the room check, so ``max_concurrent`` slice-sized reservations always fit.
_ROOM_TOLERANCE_MB = 1.0
#: How often the RSS sampler reads the process RSS while an upsert runs.
_DEFAULT_RSS_SAMPLE_MS = 100.0


def _rss_retention(environ: Mapping[str, str] = os.environ) -> float:
    """RSS per in-use byte for this process's allocator settings.

    glibc reads ``MALLOC_MMAP_THRESHOLD_`` at startup from this same environment, so the variable
    says which retention applies. ``DELTALITE_GOVERNOR_RSS_RETENTION`` overrides both.
    """
    explicit = environ.get("DELTALITE_GOVERNOR_RSS_RETENTION", "").strip()
    if explicit:
        try:
            return max(1.0, float(explicit))
        except ValueError:
            logger.warning("invalid DELTALITE_GOVERNOR_RSS_RETENTION=%r; ignoring it", explicit)
    threshold = environ.get("MALLOC_MMAP_THRESHOLD_", "").strip()
    try:
        if threshold and int(threshold) <= _LOW_MMAP_THRESHOLD_BYTES:
            return _RSS_RETENTION_LOW_MMAP_THRESHOLD
    except ValueError:
        pass
    return _RSS_RETENTION_GLIBC_DEFAULT


@frozen
class PartitionShape:
    """The part of one touched partition that sizes its worker."""

    #: Stored bytes of the largest files the merge can rewrite, largest first. Only as many as one
    #: worker can read at once are kept; each bounds the row group a reader fetches.
    largest_file_bytes: tuple[int, ...]
    #: All candidate files in the partition, and their stored bytes.
    files: int
    stored_bytes: int
    #: Bytes of the source rows that land in this partition.
    source_bytes: int = 0

    @staticmethod
    def of(file_bytes: Sequence[int], source_bytes: int = 0) -> PartitionShape:
        ordered = sorted(file_bytes, reverse=True)
        return PartitionShape(
            largest_file_bytes=tuple(ordered[:_MAX_PARALLEL_FILES]),
            files=len(ordered),
            stored_bytes=sum(ordered),
            source_bytes=source_bytes,
        )


@frozen
class RewriteProfile:
    """The touched partitions of one merge, read from the table's add actions."""

    #: One entry per touched partition, including partitions that only receive inserts.
    partitions: tuple[PartitionShape, ...]
    #: Files in the whole table. deltalite holds an add action for each of them.
    table_files: int = 0
    #: The table's ``delta.targetFileSize``, which deltalite uses as its write-buffer flush point.
    target_file_size: int = _DEFAULT_TARGET_FILE_SIZE

    @property
    def files(self) -> int:
        return sum(p.files for p in self.partitions)

    @property
    def total_mb(self) -> float:
        return sum(p.stored_bytes for p in self.partitions) / MB

    @property
    def max_row_group_mb(self) -> float:
        """Upper bound on the largest row group a reader fetches: the largest candidate file.

        Add actions carry each file's size but not its row-group count, and the footer that has it
        costs one request per file. A file holds at least one row group, so its size bounds its
        largest one. The bound is exact for single-row-group files, which is what deltalite and
        delta-rs write while a file stays under the 1M-row row-group limit. For files with several
        row groups it over-counts (about 1.5× on 2–3 row-group files), so it errs toward a smaller plan.
        """
        return max((p.largest_file_bytes[0] for p in self.partitions if p.largest_file_bytes), default=0) / MB


def _files_that_can_match(add_actions: pa.Table, source: pa.Table, primary_keys: Sequence[str]) -> list[bool]:
    """Per file, False when its first-PK range cannot hold any key of the batch.

    String keys are not pruned: delta truncates long string stats, so a truncated max can sit below
    a key the file holds, and pruning on it would under-count the rewrite.
    """
    everything = [True] * add_actions.num_rows
    if not primary_keys or primary_keys[0] not in source.column_names:
        return everything
    pk = primary_keys[0]
    min_col, max_col = f"min.{pk}", f"max.{pk}"
    if min_col not in add_actions.column_names or max_col not in add_actions.column_names:
        return everything
    file_min, file_max = add_actions[min_col], add_actions[max_col]
    if (
        pa.types.is_string(file_min.type)
        or pa.types.is_large_string(file_min.type)
        or pa.types.is_binary(file_min.type)
    ):
        return everything
    bounds = pc.min_max(source[pk])
    low, high = bounds["min"], bounds["max"]
    if not low.is_valid or not high.is_valid:
        return everything
    try:
        disjoint = pc.or_kleene(
            pc.less(file_max, low.cast(file_max.type)), pc.greater(file_min, high.cast(file_min.type))
        )
    except (pa.ArrowInvalid, pa.ArrowNotImplementedError, pa.ArrowTypeError):
        return everything
    # A null comparison (a file with no stats for the key) proves nothing, so the file stays.
    return [d is not True for d in disjoint.to_pylist()]


def rewrite_profile(
    add_actions: pa.Table,
    source: pa.Table,
    partition_col: str | None,
    primary_keys: Sequence[str],
    target_file_size: int = _DEFAULT_TARGET_FILE_SIZE,
) -> RewriteProfile:
    """Upper bound on the existing files a merge of ``source`` rewrites, from the table's add actions.

    A file is a candidate when it is in a partition the batch touches and its PK range overlaps the
    batch. Every candidate is counted because duplicate target keys can make one source row match
    several files. Every touched partition gets an entry with its share of the source, also when it
    has no candidate files.
    """
    if source.num_rows == 0:
        return RewriteProfile(partitions=(), table_files=add_actions.num_rows, target_file_size=target_file_size)

    if partition_col is None:
        rows_per_partition: dict[str | None, int] = {None: source.num_rows}
        file_partitions: list[str | None] = [None] * add_actions.num_rows
    else:
        counts = pc.value_counts(source[partition_col].cast(pa.string()))
        rows_per_partition = {
            value: int(count or 0)
            for value, count in zip(counts.field("values").to_pylist(), counts.field("counts").to_pylist())
        }
        file_partitions = (
            add_actions[f"partition.{partition_col}"].cast(pa.string()).to_pylist() if add_actions.num_rows else []
        )

    sizes_by_partition: dict[str | None, list[int]] = {partition: [] for partition in rows_per_partition}
    if add_actions.num_rows:
        can_match = _files_that_can_match(add_actions, source, primary_keys)
        for partition, size, candidate in zip(file_partitions, add_actions["size_bytes"].to_pylist(), can_match):
            if candidate and partition in sizes_by_partition:
                sizes_by_partition[partition].append(size or 0)

    bytes_per_row = source.nbytes / source.num_rows
    partitions = [
        PartitionShape.of(
            sizes,
            source_bytes=round(bytes_per_row * rows_per_partition[partition]),
        )
        for partition, sizes in sizes_by_partition.items()
    ]
    return RewriteProfile(
        partitions=tuple(sorted(partitions, key=lambda p: p.stored_bytes + p.source_bytes, reverse=True)),
        table_files=add_actions.num_rows,
        target_file_size=target_file_size,
    )


def _table_target_file_size(table: deltalake.DeltaTable) -> int:
    raw = table.metadata().configuration.get("delta.targetFileSize")
    try:
        return int(raw) if raw and int(raw) > 0 else _DEFAULT_TARGET_FILE_SIZE
    except ValueError:
        return _DEFAULT_TARGET_FILE_SIZE


def estimate_rewrite_profile(
    table: deltalake.DeltaTable, source: pa.Table, partition_col: str | None, primary_keys: Sequence[str]
) -> RewriteProfile | None:
    """``rewrite_profile`` for a live table, or None when its add actions cannot be read."""
    try:
        add_actions = pa.table(table.get_add_actions(flatten=True))
        return rewrite_profile(add_actions, source, partition_col, primary_keys, _table_target_file_size(table))
    except Exception as e:  # noqa: BLE001 - an estimate must never fail a write; None sizes conservatively
        logger.debug("deltalite governor: could not estimate the rewrite size: %s", e)
        return None


@frozen
class MemoryEstimate:
    """Predicted peak of one upsert, by term, in MB."""

    reader_mb: float
    writer_mb: float
    decode_mb: float
    #: Plan state, the source batch and the table snapshot.
    fixed_mb: float
    #: malloc in-use bytes at the peak: the sum of the terms above.
    inuse_mb: float
    #: ``inuse_mb`` times the allocator's retention: what the cgroup limit counts.
    rss_mb: float


@frozen
class WorkerTerms:
    """Memory terms for one partition worker."""

    reader_mb: float
    writer_mb: float
    held_mb: float


@frozen
class WorkerBounds:
    """Independent upper bounds for worker memory terms."""

    terms: tuple[WorkerTerms, ...]
    held_mb: tuple[float, ...]


def _worker_terms(shape: PartitionShape, files_per_worker: int, target_mb: float) -> WorkerTerms:
    row_groups_mb = [size / MB for size in shape.largest_file_bytes[:files_per_worker]]
    held = sum(row_groups_mb)
    pages = sum(min(_READER_PAGE_BUFFER_MB, _READER_PAGE_BUFFER_SHARE * rg) for rg in row_groups_mb)
    written = (shape.stored_bytes + shape.source_bytes) / MB
    return WorkerTerms(
        reader_mb=_READER_BYTES_PER_ROW_GROUP_BYTE * held + pages,
        writer_mb=_WRITER_BYTES_PER_TARGET_BYTE * min(target_mb, written),
        held_mb=held,
    )


def _unknown_shapes(n_partitions: int | None, source_mb: float, target_mb: float) -> tuple[PartitionShape, ...]:
    """Stand-in partitions when the add actions could not be read.

    Every worker is assumed to rewrite single-row-group files of ``target_file_size``: the largest
    row group the writers of these tables produce. The guess is conservative, so a failed estimate
    errs toward a smaller plan.
    """
    count = max(1, min(n_partitions or _MAX_PARALLEL_PARTITIONS, _MAX_PARALLEL_PARTITIONS))
    shape = PartitionShape.of([round(target_mb * MB)] * _MAX_PARALLEL_FILES, source_bytes=round(source_mb * MB / count))
    return (shape,) * count


def _costliest_workers(profile: RewriteProfile, files_per_worker: int) -> WorkerBounds:
    """Independent bounds for the costliest workers' reader/writer and decode terms."""
    target_mb = profile.target_file_size / MB
    terms = [_worker_terms(shape, files_per_worker, target_mb) for shape in profile.partitions]
    return WorkerBounds(
        terms=tuple(
            heapq.nlargest(
                _MAX_PARALLEL_PARTITIONS,
                terms,
                key=lambda worker: worker.reader_mb + worker.writer_mb,
            )
        ),
        held_mb=tuple(heapq.nlargest(_MAX_PARALLEL_PARTITIONS, (worker.held_mb for worker in terms))),
    )


def predict_upsert_memory(
    profile: RewriteProfile,
    source_mb: float,
    mpp: int,
    files_per_worker: int,
    buffered_bytes: int = _DEFAULT_BUFFERED_BYTES,
    retention: float = _RSS_RETENTION_GLIBC_DEFAULT,
    costliest: WorkerBounds | None = None,
) -> MemoryEstimate:
    """Peak memory of one upsert with ``mpp`` partition workers of ``files_per_worker`` readers.

    Reader/writer and decode occupancy use independent upper bounds across the ``mpp`` costliest
    partitions. ``costliest`` is ``_costliest_workers(profile, files_per_worker)`` when the caller
    already has it.
    """
    if costliest is None:
        costliest = _costliest_workers(profile, files_per_worker)
    workers = costliest.terms[:mpp]
    reader_mb = sum(w.reader_mb for w in workers)
    writer_mb = sum(w.writer_mb for w in workers)
    held_mb = sum(costliest.held_mb[:mpp])
    decode_mb = _DECODE_BUDGET_FILL * min(buffered_bytes / MB, _DECODED_BYTES_PER_STORED_BYTE * held_mb)
    fixed_mb = (
        _BASE_INUSE_MB
        + _SOURCE_INUSE_PER_MB * source_mb
        + (_SNAPSHOT_KB_PER_FILE * profile.table_files + _PLAN_KB_PER_CANDIDATE_FILE * profile.files) / 1024
    )
    inuse_mb = reader_mb + writer_mb + decode_mb + fixed_mb
    return MemoryEstimate(
        reader_mb=round(reader_mb, 1),
        writer_mb=round(writer_mb, 1),
        decode_mb=round(decode_mb, 1),
        fixed_mb=round(fixed_mb, 1),
        inuse_mb=round(inuse_mb, 1),
        rss_mb=round(inuse_mb * retention, 1),
    )


@dataclass(frozen=True)
class UpsertPlan:
    """A sizing decision for one upsert: the knobs, and the memory it is predicted to add."""

    max_parallel_partitions: int
    max_parallel_files: int
    max_buffered_bytes: int
    #: Predicted peak RSS this upsert adds, in MB. The slice is an RSS budget, so this is what fits it.
    predicted_peak_mb: float
    #: False when even the smallest plan exceeds the available slice.
    fits: bool
    estimate: MemoryEstimate
    probe_concurrency: int = _PROBE_CONCURRENCY

    def as_upsert_kwargs(self) -> dict[str, int]:
        return {
            "max_parallel_partitions": self.max_parallel_partitions,
            "max_parallel_files": self.max_parallel_files,
            "max_buffered_bytes": self.max_buffered_bytes,
            "probe_concurrency": self.probe_concurrency,
        }


def _reader_options(mpp: int) -> list[int]:
    """Readers per worker to try at ``mpp`` workers, most first, under ``_MAX_READERS_PER_UPSERT``."""
    widest = max(1, min(_MAX_PARALLEL_FILES, _MAX_READERS_PER_UPSERT // mpp))
    return sorted({f for f in (widest, _DEFAULT_FILES_PER_WORKER, 2, 1) if f <= widest}, reverse=True)


def size_upsert(
    available_mb: float,
    source_mb: float,
    n_partitions: int | None = None,
    rewrite: RewriteProfile | None = None,
    retention: float = _RSS_RETENTION_GLIBC_DEFAULT,
) -> UpsertPlan:
    """Pick the widest plan whose predicted peak RSS fits ``available_mb``.

    ``available_mb`` is the per-upsert memory slice, not the whole pod. Partition workers come
    first: the search starts at the most workers and, for each count, tries the most readers per
    worker before fewer. A worker's readers cost its largest row groups, so a partition of big
    single-row-group files steps its readers down before the plan loses a worker. When no plan
    fits, return one worker with one reader and ``fits=False``. The caller does not fall back on
    ``fits=False`` — it runs deltalite with that plan anyway (the memory floor, far below the MERGE)
    and flags ``capacity_exceeded``. ``rewrite=None`` (shape unknown) assumes target-sized files.
    """
    profile = rewrite
    if profile is None:
        target_mb = _DEFAULT_TARGET_FILE_SIZE / MB
        profile = RewriteProfile(partitions=_unknown_shapes(n_partitions, source_mb, target_mb))
    elif not profile.partitions:
        # An empty source touches no partition; size it as one worker that writes nothing.
        profile = RewriteProfile(
            partitions=(PartitionShape.of([]),),
            table_files=profile.table_files,
            target_file_size=profile.target_file_size,
        )

    partition_cap = min(_MAX_PARALLEL_PARTITIONS, max(1, len(profile.partitions)))
    if n_partitions is not None and n_partitions >= 1:
        partition_cap = min(partition_cap, n_partitions)

    # One pass over the partitions per reader count, however many plans are tried.
    costliest: dict[int, WorkerBounds] = {}
    for mpp in range(partition_cap, 0, -1):
        for files in _reader_options(mpp):
            if files not in costliest:
                costliest[files] = _costliest_workers(profile, files)
            estimate = predict_upsert_memory(
                profile, source_mb, mpp, files, retention=retention, costliest=costliest[files]
            )
            if estimate.rss_mb <= available_mb:
                return UpsertPlan(mpp, files, _DEFAULT_BUFFERED_BYTES, estimate.rss_mb, fits=True, estimate=estimate)

    estimate = predict_upsert_memory(profile, source_mb, 1, 1, retention=retention)
    return UpsertPlan(1, 1, _DEFAULT_BUFFERED_BYTES, estimate.rss_mb, fits=False, estimate=estimate)


# --- Reading the pod's real memory (cgroup v2, with v1 and psutil fallbacks) -----------------


class PodMemory:
    """Reads the pod's memory limit and live usage from the cgroup the process runs in.

    cgroup v2 (``memory.max`` / ``memory.current``) first, then v1
    (``memory.limit_in_bytes`` / ``memory.usage_in_bytes``), then psutil for usage on hosts with
    no cgroup (local dev / macOS). The limit is read once and cached (it does not change under a
    running pod). Usage counts page cache and every other upsert on the pod, so it sizes nothing
    here; compaction logs it as context.
    """

    _V2_MAX = "/sys/fs/cgroup/memory.max"
    _V2_CURRENT = "/sys/fs/cgroup/memory.current"
    _V1_MAX = "/sys/fs/cgroup/memory/memory.limit_in_bytes"
    _V1_CURRENT = "/sys/fs/cgroup/memory/memory.usage_in_bytes"
    # A v1 "unlimited" limit is a sentinel near the top of the address space, not a real cap.
    _V1_UNLIMITED = 0x7FFFFFFFFFFFF000

    def __init__(self, limit_override_mb: float | None = None) -> None:
        self._limit_override_mb = limit_override_mb
        self._limit_mb: float | None = None
        self._limit_read = False

    @staticmethod
    def _read_int(path: str) -> int | None:
        try:
            with open(path) as f:
                raw = f.read().strip()
        except (OSError, ValueError):
            return None
        if raw == "max":  # cgroup v2 unlimited
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    def limit_mb(self) -> float | None:
        """The pod's memory limit in MB, or None if it cannot be determined (unlimited/unreadable)."""
        if self._limit_read:
            return self._limit_mb
        self._limit_read = True
        if self._limit_override_mb is not None:
            self._limit_mb = self._limit_override_mb
            return self._limit_mb
        for path in (self._V2_MAX, self._V1_MAX):
            v = self._read_int(path)
            if v is not None and 0 < v < self._V1_UNLIMITED:
                self._limit_mb = v / MB
                return self._limit_mb
        self._limit_mb = None
        return None

    def current_mb(self) -> float | None:
        """Live memory currently used by everything in this cgroup, in MB, or None if unreadable."""
        for path in (self._V2_CURRENT, self._V1_CURRENT):
            v = self._read_int(path)
            if v is not None:
                return v / MB
        return psutil_rss_mb()


# --- Governor configuration ------------------------------------------------------------------


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("invalid %s=%r; using default %s", name, raw, default)
        return default


def _env_int(name: str, default: int) -> int:
    return int(_env_float(name, default))


@dataclass(frozen=True)
class GovernorConfig:
    """Runtime configuration, read from the environment so it can be tuned without a deploy.

    ``mode`` gates the rollout:
      * ``off``      — do nothing; upserts use deltalite's own defaults (today's behaviour).
      * ``advisory`` — compute and log/emit the decision, but still use deltalite defaults for the
                       actual write. Zero behaviour change; validates the model on prod.
      * ``enforce``  — apply the sized knobs. deltalite still always writes; only the knobs change.
    """

    mode: Mode = "advisory"
    #: Fraction of the pod limit deltalite planning may target; the rest is slack for allocator
    #: retention, pyarrow buffers and anything unmodelled.
    safety: float = 0.8
    #: Max upserts that can run concurrently in this process. The usable pod budget is divided by
    #: this so all ``max_concurrent`` upserts are guaranteed to fit at once — the guarantee that lets
    #: deltalite always write instead of falling back to the memory-hungry MERGE. Resolved by
    #: ``_resolve_max_concurrent`` (env override → settings.MAX_CONCURRENT_ACTIVITIES → default).
    max_concurrent: int = _DEFAULT_MAX_CONCURRENT
    #: Headroom held back from deltalite for everything else on the pod: full-refresh writes, the
    #: rare genuine-error MERGE fallback (its RSS tracks table size), interpreter and allocator slack.
    reserve_mb: float = 2048.0
    #: Used only when the cgroup limit is unreadable (local dev). None + unreadable ⇒ deltalite defaults.
    limit_override_mb: float | None = None
    #: Longest an enforce-mode admission waits for room before it writes anyway. The wait holds no
    #: reservation, so it can never block a release; the bound keeps a waiter from stalling its slot.
    max_wait_s: float = 60.0
    #: How often the RSS sampler reads the process RSS while an upsert runs. 0 turns sampling off.
    rss_sample_ms: float = _DEFAULT_RSS_SAMPLE_MS
    #: RSS per byte of predicted in-use memory. Read from the allocator settings by default.
    rss_retention: float = _RSS_RETENTION_GLIBC_DEFAULT

    @staticmethod
    def from_env() -> GovernorConfig:
        mode = os.environ.get("DELTALITE_GOVERNOR_MODE", "advisory").strip().lower()
        if mode not in ("off", "advisory", "enforce"):
            logger.warning("invalid DELTALITE_GOVERNOR_MODE=%r; defaulting to advisory", mode)
            mode = "advisory"
        override = os.environ.get("DELTALITE_GOVERNOR_LIMIT_MB")
        return GovernorConfig(
            mode=mode,  # type: ignore[arg-type]
            safety=_env_float("DELTALITE_GOVERNOR_SAFETY", 0.8),
            max_concurrent=GovernorConfig._resolve_max_concurrent(),
            reserve_mb=_env_float("DELTALITE_GOVERNOR_RESERVE_MB", 2048.0),
            limit_override_mb=float(override) if override else None,
            max_wait_s=max(0.0, _env_float("DELTALITE_GOVERNOR_MAX_WAIT_S", 60.0)),
            rss_sample_ms=max(0.0, _env_float("DELTALITE_GOVERNOR_RSS_SAMPLE_MS", _DEFAULT_RSS_SAMPLE_MS)),
            rss_retention=_rss_retention(),
        )

    @staticmethod
    def _resolve_max_concurrent() -> int:
        """Max concurrent upserts on this process, from the same source of truth as the worker.

        Resolution order:
          1. ``DELTALITE_GOVERNOR_MAX_CONCURRENT`` env override (ops escape hatch).
          2. A value declared by the process at startup via ``configure_process_concurrency`` — the
             v3 Kafka loader passes its ``BatchConsumer.max_concurrency`` here, since it is not a
             Temporal worker and ``MAX_CONCURRENT_ACTIVITIES`` does not describe it.
          3. ``settings.MAX_CONCURRENT_ACTIVITIES`` — what the Temporal worker is configured with.
          4. ``_DEFAULT_MAX_CONCURRENT`` with a warning, so it is visible when the slice is sized
             against a guess rather than the real concurrency.
        """
        explicit = os.environ.get("DELTALITE_GOVERNOR_MAX_CONCURRENT")
        if explicit:
            return max(1, _env_int("DELTALITE_GOVERNOR_MAX_CONCURRENT", _DEFAULT_MAX_CONCURRENT))
        if _PROCESS_MAX_CONCURRENT is not None:
            return _PROCESS_MAX_CONCURRENT
        configured = getattr(settings, "MAX_CONCURRENT_ACTIVITIES", None)
        if configured:
            return max(1, int(configured))
        logger.warning(
            "deltalite governor: neither DELTALITE_GOVERNOR_MAX_CONCURRENT nor "
            "settings.MAX_CONCURRENT_ACTIVITIES is set; sizing the per-upsert memory slice against a "
            "default of %d concurrent upserts. Set one to this worker's real concurrency.",
            _DEFAULT_MAX_CONCURRENT,
        )
        return _DEFAULT_MAX_CONCURRENT


@dataclass(frozen=False)
class Admission:
    """The knobs to write one upsert with, plus diagnostics.

    There is no "decline": deltalite ALWAYS writes. The governor only decides how many partition
    workers this upsert may use, sized to a fixed per-upsert slice of pod memory so all
    ``max_concurrent`` upserts are guaranteed to fit. If a source is so big that even one worker
    exceeds its slice, ``capacity_exceeded`` is set and we still run deltalite with the smallest
    plan (the memory floor, still far below the MERGE) rather than fall back to it.
    """

    upsert_kwargs: dict[str, int]
    mode: Mode
    predicted_peak_mb: float | None
    #: The per-upsert memory slice this upsert was sized against, in MB.
    budget_mb: float | None
    #: The max_parallel_partitions and max_parallel_files the governor would use — recorded in
    #: every mode (including advisory, where ``upsert_kwargs`` stays empty) so we can see the plan.
    planned_mpp: int | None = None
    planned_mpf: int | None = None
    #: True when even the smallest plan overflows the slice: an ops signal to chunk the source,
    #: raise the pod limit, or lower max_concurrent. Not a failure — deltalite still runs.
    capacity_exceeded: bool = False
    #: The predicted peak by term, in-use and RSS.
    estimate: MemoryEstimate | None = None
    #: Largest candidate file, the bound on the largest row group a reader fetches. None when unknown.
    max_row_group_mb: float | None = None
    #: Stored MB of all candidate files the merge can rewrite, over every touched partition.
    rewrite_total_mb: float | None = None
    rewrite_files: int | None = None
    #: Upserts admitted in this process at admission, this one included (every mode but off).
    concurrent_upserts: int | None = None
    #: What the RSS sampler saw from admission to release. Process-wide: see ``RssPeakSampler``.
    rss: RssWindow | None = field(default=None)
    #: Slices this upsert holds (enforce) or would hold (advisory). Above 1 when even the smallest
    #: plan overflows.
    reserved_slots: float | None = None
    #: Time spent waiting for room before the write, and whether the wait ran out.
    wait_ms: int = 0
    wait_timed_out: bool = False


# --- The governor ----------------------------------------------------------------------------


class MemoryGovernor:
    """Process-wide admission control for deltalite upserts. Construct one per process.

    State is guarded by a ``threading.Lock``, not an ``asyncio.Lock``, on purpose: the V3 loader
    runs concurrent ``process_message`` calls in worker threads, each driving ``DeltaWriter.write``
    through ``async_to_sync`` on its own short-lived event loop. An ``asyncio.Lock`` binds to the
    first loop that touches it and is not thread-safe, so a governor singleton shared across those
    per-thread loops would error or race. The critical sections here are tiny and fully synchronous
    (a few arithmetic ops, no ``await`` inside, and the lock is never held across the ``yield``), so
    a plain thread lock is both correct across loops and effectively uncontended.
    """

    def __init__(
        self,
        config: GovernorConfig | None = None,
        pod: PodMemory | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rss_sampler: RssPeakSampler | None = None,
    ) -> None:
        self.config = config or GovernorConfig.from_env()
        self.pod = pod or PodMemory(limit_override_mb=self.config.limit_override_mb)
        self._lock = threading.Lock()
        self._reserved_mb = 0.0
        self._inflight = 0
        self._clock = clock
        self._sleep = sleep
        #: Tickets of admissions waiting for room, oldest first.
        self._waiters: deque[int] = deque()
        self._next_ticket = 0
        #: Admissions in flight in every mode but off, for the concurrency the logs report.
        self._active = 0
        self._sampler = rss_sampler
        if self._sampler is None and self.config.rss_sample_ms > 0:
            self._sampler = RssPeakSampler(self.config.rss_sample_ms / 1000)

    # -- accounting --------------------------------------------------------------------------

    def _per_upsert_budget_mb(self, limit_mb: float) -> float:
        """The fixed memory slice one upsert may size itself to.

        ``(usable pod memory) / max_concurrent`` — so however many upserts run at once (up to
        ``max_concurrent``), the sum of their sized peaks stays under the pod. This static division
        is the capacity guarantee that lets deltalite always write without ever falling back to the
        memory-hungry MERGE for capacity reasons.
        """
        usable = limit_mb * self.config.safety - self.config.reserve_mb
        return max(0.0, usable) / self.config.max_concurrent

    def slot_budget_mb(self) -> float | None:
        """The memory slice one load slot may use, or None when the pod's limit is unreadable."""
        limit_mb = self.pod.limit_mb()
        return None if limit_mb is None else self._per_upsert_budget_mb(limit_mb)

    def _has_room(self, reserve_mb: float, usable_mb: float) -> bool:
        return self._reserved_mb + reserve_mb <= usable_mb + _ROOM_TOLERANCE_MB

    def _take(self, reserve_mb: float) -> None:
        self._reserved_mb += reserve_mb
        self._inflight += 1

    async def _reserve(self, reserve_mb: float, usable_mb: float) -> tuple[float, bool]:
        """Reserve ``reserve_mb`` once it fits the pod, oldest waiter first. Returns (waited_s, timed_out).

        While every upsert reserves at most one slice, ``max_concurrent`` of them always fit and
        nothing waits. Only an over-slice reservation can make the pod full. Then newcomers queue
        behind the oldest waiter rather than pile on, so the big upsert is not starved by small ones.
        A waiter holds no reservation, and a reservation is released whatever happens to its
        upsert, so a wait can only end. After ``max_wait_s`` the upsert reserves anyway and
        writes, because deltalite must always write.
        """
        with self._lock:
            if not self._waiters and self._has_room(reserve_mb, usable_mb):
                self._take(reserve_mb)
                return 0.0, False
            ticket = self._next_ticket
            self._next_ticket += 1
            self._waiters.append(ticket)
        started = self._clock()
        reserved = False
        try:
            while True:
                await self._sleep(_WAIT_POLL_S)
                with self._lock:
                    now = self._clock()
                    room = self._waiters[0] == ticket and self._has_room(reserve_mb, usable_mb)
                    if room or now - started >= self.config.max_wait_s:
                        self._waiters.remove(ticket)
                        self._take(reserve_mb)
                        reserved = True
                        return now - started, not room
        finally:
            if not reserved:
                # Cancelled while it waited: give up the place in the queue.
                with self._lock:
                    if ticket in self._waiters:
                        self._waiters.remove(ticket)

    @contextlib.asynccontextmanager
    async def admit(
        self,
        *,
        source_bytes: int,
        n_partitions: int | None = None,
        rewrite: RewriteProfile | None = None,
    ) -> AsyncIterator[Admission]:
        """Size one upsert to its memory slice and yield the knobs to run it with.

        Use as ``async with governor.admit(...) as adm``. deltalite always writes — the reservation
        is held for the whole ``with`` block and released on exit, even on exception. In enforce
        mode an upsert predicted above its slice reserves up to the whole usable pod, and entry
        waits (bounded by ``max_wait_s``) until the reservation fits beside the ones in flight.
        In every mode but off, the process RSS is sampled from the end of any wait until exit.
        """
        source_mb = source_bytes / MB

        if self.config.mode == "off":
            yield Admission({}, "off", None, None)
            return

        limit_mb = self.pod.limit_mb()
        plan: UpsertPlan | None = None
        budget_mb: float | None = None
        usable_mb = reserve_mb = 0.0
        # No cgroup limit visible (local dev / unreadable): we can't size a slice, so use deltalite's
        # own defaults. Still always deltalite.
        if limit_mb is not None:
            budget_mb = self._per_upsert_budget_mb(limit_mb)
            usable_mb = budget_mb * self.config.max_concurrent
            plan = size_upsert(budget_mb, source_mb, n_partitions, rewrite, self.config.rss_retention)
            # Capped at the usable pod so an upsert alone always fits and never waits for itself.
            reserve_mb = min(plan.predicted_peak_mb, usable_mb)

        # Only enforce reserves against the budget (and may wait for room); advisory is a pure
        # no-op on the accounting.
        admitted = False
        waited_s, timed_out = 0.0, False
        if plan is not None and self.config.mode == "enforce":
            waited_s, timed_out = await self._reserve(reserve_mb, usable_mb)
            admitted = True
        with self._lock:
            self._active += 1
            concurrent = self._active

        adm = Admission(
            upsert_kwargs=plan.as_upsert_kwargs() if plan is not None and admitted else {},
            mode=self.config.mode,
            predicted_peak_mb=plan.predicted_peak_mb if plan is not None else None,
            budget_mb=round(budget_mb, 1) if budget_mb is not None else None,
            planned_mpp=plan.max_parallel_partitions if plan is not None else None,
            planned_mpf=plan.max_parallel_files if plan is not None else None,
            capacity_exceeded=plan is not None and not plan.fits,
            estimate=plan.estimate if plan is not None else None,
            max_row_group_mb=round(rewrite.max_row_group_mb, 1) if rewrite is not None else None,
            rewrite_total_mb=round(rewrite.total_mb, 1) if rewrite is not None else None,
            rewrite_files=rewrite.files if rewrite is not None else None,
            concurrent_upserts=concurrent,
            reserved_slots=round(reserve_mb / budget_mb, 2) if budget_mb else None,
            wait_ms=round(waited_s * 1000),
            wait_timed_out=timed_out,
        )
        if plan is not None:
            self._emit_decision(adm, source_mb)
        try:
            # Sampling starts after any wait, so the window covers the write itself.
            if self._sampler is None:
                yield adm
            else:
                with self._sampler.window() as window:
                    adm.rss = window
                    yield adm
        finally:
            with self._lock:
                self._active -= 1
                if admitted:
                    self._reserved_mb -= reserve_mb
                    self._inflight -= 1

    # -- observability -----------------------------------------------------------------------

    def _emit_decision(self, adm: Admission, source_mb: float) -> None:
        """Log the decision and emit metrics. Never raises into the write path."""
        if adm.capacity_exceeded:
            logger.warning(
                "deltalite governor: source %.0f MB with %.0f MB row groups exceeds its %.0f MB "
                "per-upsert slice (max_concurrent=%d); running deltalite at mpp=1, mpf=1 and "
                "reserving %.2f slices (waited %d ms, timed out: %s).",
                source_mb,
                adm.max_row_group_mb or 0.0,
                adm.budget_mb or 0.0,
                self.config.max_concurrent,
                adm.reserved_slots or 0.0,
                adm.wait_ms,
                adm.wait_timed_out,
            )
        try:
            from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.metrics import (
                DELTALITE_GOVERNOR_DECISION_TOTAL,
                DELTALITE_GOVERNOR_INFLIGHT,
                DELTALITE_GOVERNOR_PREDICTED_PEAK_MB,
                DELTALITE_GOVERNOR_RESERVED_MB,
            )

            outcome = "capacity_exceeded" if adm.capacity_exceeded else "admitted"
            DELTALITE_GOVERNOR_DECISION_TOTAL.labels(mode=adm.mode, outcome=outcome).inc()
            DELTALITE_GOVERNOR_INFLIGHT.set(self._inflight)
            DELTALITE_GOVERNOR_RESERVED_MB.set(self._reserved_mb)
            if adm.predicted_peak_mb is not None:
                DELTALITE_GOVERNOR_PREDICTED_PEAK_MB.observe(adm.predicted_peak_mb)
        except Exception:  # noqa: BLE001 - metrics are best-effort; never fail a write over them
            pass


_GOVERNOR: MemoryGovernor | None = None


def configure_process_concurrency(max_concurrent: int) -> None:
    """Declare this process's real max concurrent upserts, from its own source of truth.

    The v3 loader calls this with its ``BatchConsumer.max_concurrency`` at startup, before the first
    upsert, so the governor sizes each memory slice against the loader's actual concurrency instead
    of the Temporal-only ``MAX_CONCURRENT_ACTIVITIES`` (unset there) or a conservative default. Takes
    precedence over the setting; the ``DELTALITE_GOVERNOR_MAX_CONCURRENT`` env override still wins.
    Resets the singleton so the next ``get_governor()`` rebuilds with the declared value.
    """
    global _PROCESS_MAX_CONCURRENT, _GOVERNOR
    _PROCESS_MAX_CONCURRENT = max(1, int(max_concurrent))
    _GOVERNOR = None


def get_governor() -> MemoryGovernor:
    """The process-wide governor singleton, built lazily from the environment on first use."""
    global _GOVERNOR
    if _GOVERNOR is None:
        _GOVERNOR = MemoryGovernor()
    return _GOVERNOR


def reset_governor_for_tests(governor: MemoryGovernor | None = None) -> None:
    """Swap the process singleton — tests only."""
    global _GOVERNOR
    _GOVERNOR = governor
