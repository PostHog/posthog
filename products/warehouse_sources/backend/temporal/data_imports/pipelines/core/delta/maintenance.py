import os
import json
import time
import asyncio
import datetime as dt
import resource
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from typing import TYPE_CHECKING, Any, cast

from django.conf import settings

import deltalake
import pyarrow.fs as pa_fs
import pyarrow.parquet as pq
import posthoganalytics
import deltalake.exceptions
from deltalake.fs import DeltaStorageHandler

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async_pool
from posthog.utils import get_machine_id

from products.warehouse_sources.backend.models.external_data_schema import update_sync_type_config_keys
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.deltalite_handles import (
    get_handle_cache,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.errors import (
    TransientObjectStoreError,
    is_offset_overflow_compaction_error,
    is_transient_maintenance_error,
    is_transient_object_store_error,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.memory_governor import get_governor
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.ops import (
    OBJECT_STORE_PERMISSION_DENIED_MESSAGE,
    OBJECT_STORE_TRANSIENT_MESSAGE,
    ObjectStorePermissionDeniedError,
    execute_with_conflict_retry,
    is_object_store_permission_denied,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.writer import _delta_table_identity
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.post_load_phases import (
    note_post_load_phase,
    recorded_phase,
)

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import DeltaTableRef

# A defensive compact fires when EITHER threshold is exceeded.
#
# Calibrated against the production file-count distribution (delta merge stats across
# all teams): total files per table sit at p50≈60, p90≈470, p95≈850, with a long tail
# (p99≈12k → ~14s merges; an observed pathological case hit ~82k files → ~45s merges).
# Merge planning time tracks TOTAL files, not files-per-partition — delta still
# enumerates every file's metadata even when partition pruning skips reading them — so
# we gate on both:
#
# - files-per-partition: bounds per-partition fragmentation and rescues partitioned
#   (esp. md5) tables, where a merge touches every partition. 200 sits well above the
#   healthy steady state (compaction runs at the end of each successful sync) yet
#   triggers long before a table reaches the slow tail.
# - total files: a partition-count-independent backstop so a table with a high
#   partition_count can't accumulate tens of thousands of files (each adding to merge
#   planning time) while staying under the per-partition bar. 5,000 is above p95 (~850)
#   — so healthy tables never trip it — and well below the p99/pathological tail.
#
# Either count only starts a compaction when compaction can remove enough files (see
# `_count_trigger_can_compact`). A table with one file in each of many partitions stays over the
# total-files bar after any compaction.
#
# Tune further once the admin fragmentation view gives per-customer distributions.
DEFAULT_COMPACT_FILES_PER_PARTITION_THRESHOLD = 200
DEFAULT_COMPACT_TOTAL_FILES_THRESHOLD = 5000

# Post-load triggers on the files a compaction would remove (see `removable_file_count`). The
# averages above cannot see an incremental table's newest partition, because its older partitions
# keep the average near one file each. The table-wide trigger covers partitions that each keep a few,
# and only runs when the vacuum is due: an md5 table gets a small file in every bucket on each sync,
# so a table-wide count checked on every sync would compact the whole table every time.
DEFAULT_COMPACT_REMOVABLE_FILES_PER_PARTITION_THRESHOLD = 8
DEFAULT_COMPACT_REMOVABLE_FILES_THRESHOLD = 100

# delta-rs's own default target size for a compaction rewrite bin when none is given (see
# `delta.targetFileSize`, or 100MB absent that table property). Starting the retry ladder here
# instead of passing None keeps every attempt's size explicit and halvable.
DEFAULT_COMPACT_TARGET_SIZE_BYTES = 100 * 1024 * 1024
# Halving the bin size on a byte-array-offset-overflow panic (see is_offset_overflow_compaction_error)
# shrinks how many files get concatenated into one Arrow batch. Bounded so a table whose overflow
# can't be avoided at any reasonable bin size still surfaces to error tracking instead of looping.
COMPACT_OFFSET_OVERFLOW_RETRIES = 3

# delta-rs bins files by their compressed size but holds each bin decoded while it rewrites it, so a
# bin of highly compressible text (JSON documents, say) can decode to many times its target size.
# Keep one bin's decoded bytes at half the 2 GiB Arrow offset limit, and inside the load slot the
# compaction runs in. A running task holds its bin's decoded batches plus the writer's buffers for
# the file it produces, so it is budgeted at twice the decoded bin. delta-rs also leaves every file larger
# than the target out of the bins, so the target bounds the largest file that a compaction decodes.
COMPACT_MAX_DECODED_BIN_BYTES = 1024 * 1024 * 1024
COMPACT_MIN_TARGET_SIZE_BYTES = 8 * 1024 * 1024
_COMPACT_TASK_MEMORY_FACTOR = 2
# Footers of the largest files only: compacted files are the largest, and they set the worst case.
_COMPACT_RATIO_SAMPLE_FILES = 2


@frozen
class CompactionPlan:
    target_size: int | None
    max_concurrent_tasks: int | None
    compression_ratio: float | None
    slot_budget_mb: float | None


def plan_compaction(compression_ratio: float | None, slot_budget_mb: float | None) -> CompactionPlan:
    """Bin size and parallelism that keep one compaction inside its memory slot."""
    rounded_ratio = round(compression_ratio, 2) if compression_ratio is not None else None
    rounded_slot = round(slot_budget_mb, 1) if slot_budget_mb is not None else None
    if compression_ratio is None or (slot_budget_mb is not None and slot_budget_mb <= 0):
        return CompactionPlan(
            target_size=None,
            max_concurrent_tasks=None,
            compression_ratio=rounded_ratio,
            slot_budget_mb=rounded_slot,
        )

    ratio = max(compression_ratio, 1.0)
    decoded_cap = float(COMPACT_MAX_DECODED_BIN_BYTES)
    slot_budget_bytes = slot_budget_mb * 1024 * 1024 if slot_budget_mb is not None else None
    if slot_budget_bytes is not None:
        decoded_cap = min(decoded_cap, slot_budget_bytes / _COMPACT_TASK_MEMORY_FACTOR)
    safe_target_size = decoded_cap / ratio
    if safe_target_size < COMPACT_MIN_TARGET_SIZE_BYTES:
        return CompactionPlan(
            target_size=None,
            max_concurrent_tasks=None,
            compression_ratio=rounded_ratio,
            slot_budget_mb=rounded_slot,
        )

    target_size = int(min(DEFAULT_COMPACT_TARGET_SIZE_BYTES, safe_target_size))
    max_concurrent_tasks = None
    if slot_budget_bytes is not None:
        per_task_bytes = target_size * ratio * _COMPACT_TASK_MEMORY_FACTOR
        max_concurrent_tasks = max(1, min(os.cpu_count() or 1, int(slot_budget_bytes // per_task_bytes)))
    return CompactionPlan(
        target_size=target_size,
        max_concurrent_tasks=max_concurrent_tasks,
        compression_ratio=rounded_ratio,
        slot_budget_mb=rounded_slot,
    )


def _sample_compression_ratio(table: deltalake.DeltaTable) -> float | None:
    """Decoded bytes per stored byte, from the footers of the table's largest files, or None if unreadable.

    Reads the sampled footers directly. `to_pyarrow_dataset` builds a fragment for every live file
    first, which costs seconds and a gigabyte of memory on a table with ten thousand files.
    """
    sizes = table._table.get_add_file_sizes()
    largest = dict(sorted(sizes.items(), key=lambda item: -(item[1] or 0))[:_COMPACT_RATIO_SAMPLE_FILES])
    if not largest:
        return None
    handler = DeltaStorageHandler.from_table(table._table, table._storage_options, largest)
    filesystem = pa_fs.PyFileSystem(cast(pa_fs.FileSystemHandler, handler))
    decoded = stored = 0
    for path in largest:
        metadata = pq.read_metadata(path, filesystem=filesystem)
        for index in range(metadata.num_row_groups):
            row_group = metadata.row_group(index)
            decoded += row_group.total_byte_size
            stored += sum(row_group.column(column).total_compressed_size for column in range(row_group.num_columns))
    return decoded / stored if stored else None


def _peak_rss_mb() -> float:
    # ru_maxrss is KiB on Linux, the platform this runs on.
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)


# How long a tombstoned file survives before vacuum may delete it. Readers that pin an older
# table version must stay inside this window — see MAX_SNAPSHOT_ROLLBACK in the fan-out
# warehouse-parent reader, which derives its bound from this value.
VACUUM_RETENTION = dt.timedelta(hours=24)

# A checkpoint drops tombstones older than `delta.deletedFileRetentionDuration` (delta's default,
# which these tables keep). A lite vacuum finds dead files only through tombstones, so a file whose
# tombstone was dropped before a vacuum ran is never deleted. A vacuum must run within this window,
# less the retention, after each tombstone.
DELTA_DELETED_FILE_RETENTION = dt.timedelta(days=7)


def removable_file_count(file_sizes: Iterable[int], target_size: int = DEFAULT_COMPACT_TARGET_SIZE_BYTES) -> int:
    """The fewest files a compaction is sure to remove from one partition, given the sizes of its files.

    delta-rs keeps a partition's files in their original order and packs neighbours into bins up to the
    target size. A file at or above the target splits the run around it, and a bin with one file is
    skipped. The log's file sizes do not show that order, so this assumes the worst case: every file of
    at least half the target separates the small files around it. A compaction usually writes files of
    that size, so they must not count as small. Inside a run, every bin but the last is more than half
    full, because the next small file did not fit. A count above zero therefore always means a
    compaction that removes files, and a layout that compaction cannot improve never starts one.
    """
    sizes = list(file_sizes)
    small = [size for size in sizes if size < target_size // 2]
    runs = len(sizes) - len(small) + 1
    output_files = runs + 2 * sum(small) // target_size
    return max(0, len(small) - output_files)


@frozen
class _PartitionFileStats:
    size_bytes: int
    removable_files: int


def _partition_file_stats(
    table: deltalake.DeltaTable, target_size: int = DEFAULT_COMPACT_TARGET_SIZE_BYTES
) -> list[_PartitionFileStats]:
    """Stats for each partition, read from the Delta log with no S3 request."""
    # Each partition value is one directory, and an unpartitioned table keeps its files at the root.
    sizes: defaultdict[str, list[int]] = defaultdict(list)
    for path, size in table._table.get_add_file_sizes().items():
        sizes[path.rpartition("/")[0]].append(size or 0)
    return [
        _PartitionFileStats(
            size_bytes=sum(partition_sizes),
            removable_files=removable_file_count(partition_sizes, target_size),
        )
        for partition_sizes in sizes.values()
    ]


@frozen
class _SmallFileFragmentation:
    fragmented: bool
    max_removable: int
    total_removable: int
    compactable_over_budget: bool


def _small_file_fragmentation(
    partitions: Iterable[_PartitionFileStats], table_wide_small_files: bool
) -> _SmallFileFragmentation:
    partitions = list(partitions)
    max_removable = max((partition.removable_files for partition in partitions), default=0)
    total_removable = sum(partition.removable_files for partition in partitions)
    budget = settings.DATA_WAREHOUSE_TARGET_PARTITION_BYTES
    compactable_over_budget = any(
        partition.size_bytes > budget and partition.removable_files > 0 for partition in partitions
    )
    fragmented = (
        max_removable >= DEFAULT_COMPACT_REMOVABLE_FILES_PER_PARTITION_THRESHOLD
        or (table_wide_small_files and total_removable >= DEFAULT_COMPACT_REMOVABLE_FILES_THRESHOLD)
        or compactable_over_budget
    )
    return _SmallFileFragmentation(
        fragmented=fragmented,
        max_removable=max_removable,
        total_removable=total_removable,
        compactable_over_budget=compactable_over_budget,
    )


def _count_trigger_can_compact(small_files: _SmallFileFragmentation) -> bool:
    # The count triggers exist to lower the file count, so they need a compaction that removes files
    # in quantity. The table-wide count always applies here: the table is already over a count bar.
    return (
        small_files.max_removable >= DEFAULT_COMPACT_REMOVABLE_FILES_PER_PARTITION_THRESHOLD
        or small_files.total_removable >= DEFAULT_COMPACT_REMOVABLE_FILES_THRESHOLD
    )


@frozen
class VacuumCadence:
    commit_threshold: int
    max_interval: dt.timedelta
    full_interval: dt.timedelta

    @classmethod
    def from_settings(cls) -> "VacuumCadence":
        return cls(
            commit_threshold=settings.DATA_WAREHOUSE_VACUUM_COMMIT_THRESHOLD,
            max_interval=dt.timedelta(hours=settings.DATA_WAREHOUSE_VACUUM_MAX_INTERVAL_HOURS),
            full_interval=dt.timedelta(hours=settings.DATA_WAREHOUSE_FULL_VACUUM_INTERVAL_HOURS),
        )


@frozen
class _VacuumConfigKeys:
    version: str
    vacuumed_at: str
    full_vacuumed_at: str


@frozen
class VacuumWatermarks:
    """The vacuum cadence state of one Delta table, persisted in the schema's `sync_type_config`.

    One schema can back two Delta tables (the snapshot and its `_cdc` companion). Their versions are
    unrelated numbers, so each table keeps its own keys.
    """

    version: int | None
    vacuumed_at: dt.datetime | None
    full_vacuumed_at: dt.datetime | None

    @staticmethod
    def _keys(is_cdc_companion: bool) -> _VacuumConfigKeys:
        suffix = "_cdc" if is_cdc_companion else ""
        return _VacuumConfigKeys(
            version=f"last_vacuum_version{suffix}",
            vacuumed_at=f"last_vacuum_at{suffix}",
            full_vacuumed_at=f"last_full_vacuum_at{suffix}",
        )

    @classmethod
    def from_config(cls, config: Mapping[str, Any] | None, is_cdc_companion: bool) -> "VacuumWatermarks":
        keys = cls._keys(is_cdc_companion)
        config = config or {}
        return cls(
            version=config.get(keys.version),
            vacuumed_at=_parse_timestamp(config.get(keys.vacuumed_at)),
            full_vacuumed_at=_parse_timestamp(config.get(keys.full_vacuumed_at)),
        )

    def config_updates(self, previous: "VacuumWatermarks", is_cdc_companion: bool) -> dict[str, Any]:
        keys = self._keys(is_cdc_companion)
        updates: dict[str, Any] = {}
        if self.version is not None and self.version != previous.version:
            updates[keys.version] = self.version
        if self.vacuumed_at is not None and self.vacuumed_at != previous.vacuumed_at:
            updates[keys.vacuumed_at] = self.vacuumed_at.isoformat()
        if self.full_vacuumed_at is not None and self.full_vacuumed_at != previous.full_vacuumed_at:
            updates[keys.full_vacuumed_at] = self.full_vacuumed_at.isoformat()
        return updates


def _parse_timestamp(value: Any) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=dt.UTC)


@frozen
class VacuumDecision:
    # None when no vacuum is due. Otherwise "full", "commits" or "time".
    reason: str | None
    commits_since_vacuum: int
    # The watermarks with every missing or stale value seeded, whether a vacuum runs or not.
    watermarks: VacuumWatermarks

    @property
    def full(self) -> bool:
        return self.reason == "full"


def decide_vacuum(
    watermarks: VacuumWatermarks, cadence: VacuumCadence, version: int, now: dt.datetime
) -> VacuumDecision:
    """Which vacuum, if any, this pass runs.

    A missing watermark is seeded without a vacuum, so the tables that existed before a watermark do
    not all vacuum at the same time after a deploy. A version above the table's current version means
    the table was recreated (delta versions are monotonic within one incarnation), and no reset path
    clears the persisted watermark. Left alone, it would block the commit cadence until the new table
    out-versioned the old one, so it is seeded again.

    The commit cadence alone lets a table that commits slowly go past the tombstone window (see
    `DELTA_DELETED_FILE_RETENTION`), so a lite vacuum also runs when `max_interval` has passed. A lite
    vacuum never finds files that no tombstone names: files a crashed writer left, or files whose
    tombstone was dropped. A full vacuum lists the table instead, and runs once each `full_interval`.
    A full vacuum also deletes everything that a lite vacuum deletes, so it replaces a lite one.
    """
    version_stale = watermarks.version is None or version < watermarks.version
    seeded = VacuumWatermarks(
        version=version if version_stale else watermarks.version,
        vacuumed_at=watermarks.vacuumed_at or now,
        full_vacuumed_at=watermarks.full_vacuumed_at or now,
    )
    reason = None
    if watermarks.full_vacuumed_at is not None and now - watermarks.full_vacuumed_at >= cadence.full_interval:
        reason = "full"
    elif watermarks.version is not None and not version_stale:
        if version - watermarks.version >= cadence.commit_threshold:
            reason = "commits"
    if reason is None and watermarks.vacuumed_at is not None and now - watermarks.vacuumed_at >= cadence.max_interval:
        reason = "time"
    return VacuumDecision(reason=reason, commits_since_vacuum=version - (seeded.version or 0), watermarks=seeded)


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class DeltaMaintenance:
    """Compaction, vacuuming, and the vacuum-watermark cadence for one schema's Delta table.

    Stateless over a `DeltaTableRef`, which holds the cached table handle — construct one at the
    call site whenever maintenance is needed. `run_scheduled` is the policy entry point shared by
    the pre-write defensive pass (both pipelines, so a sync that arrived at a fragmented table
    cleans up before adding to the pile) and the post-load pass.
    """

    def __init__(self, table: "DeltaTableRef", *, clock: Callable[[], dt.datetime] = _utc_now) -> None:
        self._table = table
        self._logger = table.logger
        self._clock = clock

    @recorded_phase("vacuum")
    async def _vacuum(self, table: deltalake.DeltaTable, *, full: bool = False) -> int:
        await self._logger.adebug("Vacuuming table...", vacuum_full=full)
        # vacuum() commits a REMOVE of tombstoned files, so it's just as subject to delta-rs's
        # conflict checker as merge/optimize.compact — see execute_with_conflict_retry.
        vacuum_stats = await execute_with_conflict_retry(
            table,
            lambda: table.vacuum(
                retention_hours=int(VACUUM_RETENTION.total_seconds() // 3600),
                enforce_retention_duration=False,
                dry_run=False,
                full=full,
            ),
            "vacuum_table",
            self._logger,
        )
        note_post_load_phase(files_deleted=len(vacuum_stats) if isinstance(vacuum_stats, list) else None)
        await self._logger.adebug(json.dumps(vacuum_stats))
        return len(vacuum_stats) if isinstance(vacuum_stats, list) else 0

    async def _plan_compaction(self, table: deltalake.DeltaTable) -> CompactionPlan:
        try:
            ratio = await asyncio.to_thread(_sample_compression_ratio, table)
        except Exception as e:
            await self._logger.awarning(f"compact: could not sample the compression ratio: {e}")
            ratio = None
        return plan_compaction(ratio, get_governor().slot_budget_mb())

    @recorded_phase("compact")
    async def _compact(self, table: deltalake.DeltaTable, plan: CompactionPlan | None = None) -> bool:
        plan = plan or await self._plan_compaction(table)
        target_size = plan.target_size
        if target_size is None:
            await self._logger.awarning(
                "compact: skipping because no memory-safe plan is available",
                compact_compression_ratio=plan.compression_ratio,
                compact_slot_budget_mb=plan.slot_budget_mb,
            )
            return False
        max_concurrent_tasks = plan.max_concurrent_tasks
        pod_mb_before = get_governor().pod.current_mb()
        started = time.monotonic()
        await self._logger.ainfo(
            "Compacting table...",
            compact_engine="delta-rs",
            compact_target_size=target_size,
            compact_max_concurrent_tasks=max_concurrent_tasks,
            compact_compression_ratio=plan.compression_ratio,
            compact_slot_budget_mb=plan.slot_budget_mb,
            pod_memory_mb=pod_mb_before,
            peak_rss_mb=_peak_rss_mb(),
        )
        attempt = 0
        while True:

            def _compact_op(size: int = target_size, tasks: int | None = max_concurrent_tasks) -> dict[str, Any]:
                return table.optimize.compact(target_size=size, max_concurrent_tasks=tasks)

            try:
                compact_stats = await execute_with_conflict_retry(
                    table,
                    _compact_op,
                    "compact",
                    self._logger,
                )
                break
            except deltalake.exceptions.DeltaError as e:
                if not is_offset_overflow_compaction_error(e) or attempt >= COMPACT_OFFSET_OVERFLOW_RETRIES:
                    raise
                attempt += 1
                target_size //= 2
                # The failed attempt's memory may not be freed yet, so the retry runs one bin at a time.
                max_concurrent_tasks = 1
                await self._logger.awarning(
                    f"compact: byte array offset overflow, retrying with smaller "
                    f"target_size={target_size} (attempt {attempt}/{COMPACT_OFFSET_OVERFLOW_RETRIES})",
                    pod_memory_mb=get_governor().pod.current_mb(),
                    peak_rss_mb=_peak_rss_mb(),
                )
        await self._logger.ainfo(
            "compact: done",
            compact_engine="delta-rs",
            compact_duration_s=round(time.monotonic() - started, 1),
            compact_files_added=compact_stats.get("numFilesAdded"),
            compact_files_removed=compact_stats.get("numFilesRemoved"),
            pod_memory_mb=get_governor().pod.current_mb(),
            peak_rss_mb=_peak_rss_mb(),
        )
        note_post_load_phase(
            files_added=compact_stats.get("numFilesAdded"), files_removed=compact_stats.get("numFilesRemoved")
        )
        await self._logger.adebug(json.dumps(compact_stats))
        return True

    async def _compact_with_deltalite(self, table: deltalake.DeltaTable) -> bool | None:
        """Compact through deltalite's native compaction. None means delta-rs must compact instead.

        deltalite streams each bin under byte budgets and caps every output file by its decoded size,
        so it needs no compression-ratio sample and no offset-overflow retry ladder. It also retries its
        own commit conflicts, and keeps each bin whose input files are still live.
        """
        try:
            import deltalite  # noqa: PLC0415 - keeps deltalite off the import path while the setting is off
        except ImportError:
            await self._log_compact_fallback("deltalite_not_installed")
            return None
        if not hasattr(deltalite.DeltaLiteTable, "compact"):
            await self._log_compact_fallback("deltalite_compact_unavailable")
            return None

        uri = await self._table.get_table_uri()
        storage_options = self._table.get_storage_options()
        identity = _delta_table_identity(table, self._table)
        slot_budget_mb = get_governor().slot_budget_mb()
        compact_kwargs: dict[str, Any] = {
            "target_file_size": DEFAULT_COMPACT_TARGET_SIZE_BYTES,
            # deltalite lowers this until the bins in flight fit the slot budget.
            "max_parallel_bins": os.cpu_count() or 1,
            "slot_budget_bytes": int(slot_budget_mb * 1024 * 1024) if slot_budget_mb else None,
            # These keys must never include the loader's `run_uuid`/`batch_index` tags, because
            # `has_batch_been_committed` would then read a compaction as a committed batch.
            "commit_metadata": {"compact_engine": "deltalite", "job_id": str(self._table.job.id)},
            "min_partition_removable_files": 1,
        }

        def _run() -> dict[str, Any]:
            if identity is None:
                return deltalite.DeltaLiteTable.open(uri, storage_options).compact(**compact_kwargs)
            table_id, table_version = identity
            with get_handle_cache().lease(
                uri, storage_options=storage_options, table_id=table_id, table_version=table_version
            ) as handle:
                return handle.compact(**compact_kwargs)

        pod_mb_before = get_governor().pod.current_mb()
        started = time.monotonic()
        await self._logger.ainfo(
            "Compacting table...",
            compact_engine="deltalite",
            compact_target_size=DEFAULT_COMPACT_TARGET_SIZE_BYTES,
            compact_max_parallel_bins=compact_kwargs["max_parallel_bins"],
            compact_slot_budget_mb=round(slot_budget_mb, 1) if slot_budget_mb is not None else None,
            pod_memory_mb=pod_mb_before,
            peak_rss_mb=_peak_rss_mb(),
        )
        try:
            compact_stats = await asyncio.to_thread(_run)
        except deltalite.DeltaLiteUnsupportedTableError:
            await self._log_compact_fallback("unsupported_table")
            return None
        except deltalite.DeltaLiteCommitConflictError:
            # The retries ran out, or a concurrent writer changed the schema or the partitioning.
            # Nothing was committed, and the next maintenance pass compacts the table again.
            await self._logger.awarning("compact: deltalite lost to a concurrent commit, not reporting")
            return False
        except Exception as e:
            # The object-store classifiers match the error text, but accept only OS and delta-rs errors.
            as_os_error = OSError(str(e))
            if is_object_store_permission_denied(as_os_error):
                await self._logger.awarning(f"compact: the object store denied the operation ({type(e).__name__})")
                raise ObjectStorePermissionDeniedError(OBJECT_STORE_PERMISSION_DENIED_MESSAGE) from e
            if is_transient_object_store_error(as_os_error):
                await self._logger.awarning("compact: transient object-store error, not reporting")
                raise TransientObjectStoreError(OBJECT_STORE_TRANSIENT_MESSAGE) from e
            # A failed deltalite compaction commits nothing and deletes its output files, so delta-rs
            # can compact the same table safely.
            capture_exception(e)
            await self._log_compact_fallback("deltalite_error")
            return None

        commits = compact_stats.get("commits")
        if isinstance(commits, int) and commits > 0:
            # The delta-rs handle is now behind the log. Marking it stale makes the next reader refresh it.
            version = compact_stats.get("version")
            self._table.note_deltalite_commit(version if isinstance(version, int) else None)
        await self._logger.ainfo(
            "compact: done",
            compact_engine="deltalite",
            compact_duration_s=round(time.monotonic() - started, 1),
            compact_files_added=compact_stats.get("numFilesAdded"),
            compact_files_removed=compact_stats.get("numFilesRemoved"),
            compact_commits=commits,
            compact_commit_retries=compact_stats.get("commit_retries"),
            compact_bins=compact_stats.get("bins"),
            compact_bins_dropped=compact_stats.get("bins_dropped"),
            compact_parallel_bins=compact_stats.get("parallel_bins"),
            pod_memory_mb=get_governor().pod.current_mb(),
            peak_rss_mb=_peak_rss_mb(),
        )
        await self._logger.adebug(json.dumps(compact_stats))
        return True

    async def _log_compact_fallback(self, reason: str) -> None:
        await self._logger.ainfo(
            "compact: falling back to delta-rs",
            compact_engine="delta-rs",
            compact_fallback_reason=reason,
        )

    async def vacuum_if_due(self, watermarks: VacuumWatermarks, cadence: VacuumCadence) -> VacuumDecision | None:
        """Vacuum when the cadence says so (see `decide_vacuum`), and return the decision.

        Decoupled from merge success (called pre-write) so a table that OOMs its merge every run still
        gets cleaned. Vacuum only deletes dead files (an S3 LIST + delete), so unlike
        `compact_if_fragmented`'s `optimize.compact` (which rewrites partitions) it is memory-safe even
        on an oversized table. The cadence needs no S3 request to decide. The returned watermarks are
        the ones to persist; None means the table does not exist.
        """
        table = await self._table.get_delta_table()
        if table is None:
            return None

        version = await asyncio.to_thread(table.version)
        now = self._clock()
        decision = decide_vacuum(watermarks, cadence, version, now)
        if decision.reason is None:
            await self._logger.adebug(f"vacuum: not due, {decision.commits_since_vacuum} commits since the last vacuum")
            return decision

        await self._logger.ainfo(f"vacuum: due ({decision.reason}), vacuuming", vacuum_full=decision.full)
        started = time.monotonic()
        files_deleted = await self._vacuum(table, full=decision.full)
        # Vacuum commits its own start and end entries, which must not count towards the next cadence.
        version_after = await asyncio.to_thread(table.version)
        try:
            # Observability for the maintenance path — how often tables vacuum and how much log churn
            # accrued between vacuums. Best-effort: telemetry must never break the sync.
            posthoganalytics.capture(
                distinct_id=get_machine_id(),
                event="warehouse_delta_vacuumed",
                properties={
                    "team_id": self._table.job.team_id,
                    "schema_id": str(self._table.job.schema_id),
                    "source_id": str(self._table.job.pipeline_id),
                    "resource_name": self._table.resource_name,
                    "commits_since_last_vacuum": decision.commits_since_vacuum,
                    "delta_version": version,
                    "vacuum_reason": decision.reason,
                    "vacuum_full": decision.full,
                    "files_deleted": files_deleted,
                    "duration_s": round(time.monotonic() - started, 2),
                },
            )
        except Exception as e:
            capture_exception(e)
        return VacuumDecision(
            reason=decision.reason,
            commits_since_vacuum=decision.commits_since_vacuum,
            watermarks=VacuumWatermarks(
                version=version_after,
                vacuumed_at=now,
                full_vacuumed_at=now if decision.full else decision.watermarks.full_vacuumed_at,
            ),
        )

    async def compact_if_fragmented(
        self,
        threshold: int = DEFAULT_COMPACT_FILES_PER_PARTITION_THRESHOLD,
        total_threshold: int = DEFAULT_COMPACT_TOTAL_FILES_THRESHOLD,
        compact_small_files: bool = False,
        table_wide_small_files: bool = False,
    ) -> bool:
        """Compact if the table is fragmented past either count threshold, or has small files to merge.

        Count-fragmented = files-per-partition > `threshold` OR total files > `total_threshold`.
        The total-files backstop matters because delta enumerates every file's metadata
        during a merge even when partition pruning skips reading them, so merge planning
        time tracks total files — a high partition_count must not let a table accumulate
        tens of thousands of files while staying under the per-partition bar. A count trigger
        compacts only when compaction can remove enough files (see `_count_trigger_can_compact`):
        a table with one file in each of ten thousand partitions stays over the bar after a
        compaction, and would otherwise plan and commit a compaction on every pass.

        `compact_small_files` adds the removable-file triggers (see
        `DEFAULT_COMPACT_REMOVABLE_FILES_PER_PARTITION_THRESHOLD`), plus a trigger for any
        partition over the repartition budget that compaction can shrink. Only the non-CDC
        post-load pass sets it. The pre-write pass is a backstop for a table that arrived
        fragmented, and a CDC final lands every tick, so these triggers would compact a CDC table
        every few ticks. `table_wide_small_files` also enables the table-wide removable-file
        trigger, which `run_scheduled` sets only when a vacuum is due or ran earlier in the same sync.

        The partition count comes from the table's layout: the distinct file directories in the
        delta log, with no extra I/O. Repartition detection counts partitions the same way. The
        schema's persisted `partition_count` is the md5 bucket count, but every partition mode
        stores the source's value there, so a datetime-partitioned table can store 1 while it holds
        thousands of partition directories.

        Returns True if compaction ran, False if it was skipped. The decision reads only the
        Delta log. Runs pre-write, so a sync that arrived at a fragmented state (e.g. an earlier
        attempt that failed before reaching post-load) cleans up before adding to the pile, and
        again post-load once the sync's own files have landed. Compaction does not vacuum: the
        files it removes are younger than `VACUUM_RETENTION`, so a vacuum right after it could not
        delete them, and the vacuum cadence collects them later.
        """
        table = await self._table.get_delta_table()
        if table is None:
            return False

        file_uris = await asyncio.to_thread(table.file_uris)
        total_files = len(file_uris)
        note_post_load_phase(total_files=total_files)
        # One directory per partition value. An unpartitioned table collapses to the table root, and
        # an empty table counts as one partition for the threshold math.
        effective_partitions = max(len({uri.rsplit("/", 1)[0] for uri in file_uris}), 1)
        files_per_partition = total_files / effective_partitions

        count_fragmented = files_per_partition > threshold or total_files > total_threshold
        stats = (
            f"total_files={total_files}, partitions={effective_partitions}, "
            f"files_per_partition={files_per_partition:.1f}, threshold={threshold}, "
            f"total_threshold={total_threshold}"
        )
        if not count_fragmented and not compact_small_files:
            await self._logger.adebug(f"compact_if_fragmented: skipping ({stats})")
            return False

        def triggered(small_file_stats: _SmallFileFragmentation) -> bool:
            return (count_fragmented and _count_trigger_can_compact(small_file_stats)) or (
                compact_small_files and small_file_stats.fragmented
            )

        partitions = await asyncio.to_thread(_partition_file_stats, table, DEFAULT_COMPACT_TARGET_SIZE_BYTES)
        # Repartition detection runs after this pass and compares partition bytes to its budget.
        # Small files take more bytes at rest than the same rows after compaction, so an
        # over-budget partition that compaction can shrink must be compacted before it is measured.
        small_file_stats = _small_file_fragmentation(partitions, table_wide_small_files)
        stats += (
            f", count_fragmented={count_fragmented}, "
            f"max_removable_files_per_partition={small_file_stats.max_removable}, "
            f"removable_files={small_file_stats.total_removable}, "
            f"compactable_over_budget={small_file_stats.compactable_over_budget}"
        )
        if not triggered(small_file_stats):
            await self._logger.adebug(f"compact_if_fragmented: skipping ({stats})")
            return False

        if settings.DATA_WAREHOUSE_DELTALITE_COMPACTION:
            await self._logger.ainfo(f"compact_if_fragmented: triggering compact ({stats})")
            compacted = await self._compact_with_deltalite(table)
            if compacted is not None:
                return compacted

        plan = await self._plan_compaction(table)
        if plan.target_size is None:
            await self._compact(table, plan)
            return False

        if plan.target_size != DEFAULT_COMPACT_TARGET_SIZE_BYTES:
            # A smaller bin can merge fewer of the files, so the trigger must hold at the planned size too.
            partitions = await asyncio.to_thread(_partition_file_stats, table, plan.target_size)
            if not triggered(_small_file_fragmentation(partitions, table_wide_small_files)):
                await self._logger.adebug(
                    f"compact_if_fragmented: skipping; no files are removable at planned target_size="
                    f"{plan.target_size} ({stats})"
                )
                return False

        await self._logger.ainfo(f"compact_if_fragmented: triggering compact ({stats})")
        return await self._compact(table, plan)

    def _vacuumed_during_job(self, watermarks: VacuumWatermarks) -> bool:
        # The pre-write pass vacuums before it writes, and it never checks small files. The post-load
        # pass of the same sync then sees no vacuum due, but must still run the table-wide check.
        job_started_at = getattr(self._table.job, "created_at", None)
        if watermarks.vacuumed_at is None or not isinstance(job_started_at, dt.datetime):
            return False
        if job_started_at.tzinfo is None:
            job_started_at = job_started_at.replace(tzinfo=dt.UTC)
        return watermarks.vacuumed_at >= job_started_at

    async def run_scheduled(
        self,
        schema: "ExternalDataSchema",
        *,
        is_cdc_companion: bool = False,
        compact_small_files: bool = False,
    ) -> None:
        """Best-effort threshold maintenance owning the vacuum-watermark lifecycle for `schema`.

        Vacuums when the cadence is due (see `decide_vacuum`), persists the watermarks via
        `update_sync_type_config_keys` (row-locked merge), and then compacts if fragmented. Both call
        sites (the pre-write defensive pass and the post-load pass) share this, so the watermarks
        can't drift between them. The persisted keys are also merged into the in-memory schema, so
        the post-load pass of the same sync sees the vacuum that the pre-write pass ran.

        The vacuum runs and persists before the compaction, so a compaction that fails on every
        sync does not stop the vacuum cadence.

        One schema can back two delta tables (snapshot + `_cdc` companion) whose delta versions are
        unrelated numbers, so each table's vacuum cadence gets its own watermark keys — sharing them
        would corrupt both cadences.

        Never raises: a maintenance failure must not block the sync, and the next scheduled pass
        retries the same idempotent cleanup. A transient infra error (see
        `is_transient_maintenance_error`) — an object-store hiccup, a racy concurrent-maintenance
        DeltaError, or an app-DB connection blip — is logged at warning instead of captured.

        An object-store refusal (see is_object_store_permission_denied) is logged at warning too.
        Compaction and vacuuming only rewrite and reclaim files that the load has already committed,
        so a refused pass leaves every live row queryable and costs the table nothing but a delayed
        cleanup. It is a policy condition on our own bucket rather than a maintenance defect, so a
        report per sync would say the same thing repeatedly about something no code change fixes.
        The watermarks are not persisted either, so the cadence re-attempts the vacuum on the next
        pass instead of waiting for a cleanup that never ran.
        """
        try:
            watermarks = VacuumWatermarks.from_config(schema.sync_type_config, is_cdc_companion)

            decision = await self.vacuum_if_due(watermarks, VacuumCadence.from_settings())
            if decision is None:
                return
            updates = decision.watermarks.config_updates(watermarks, is_cdc_companion)
            if updates:
                await database_sync_to_async_pool(update_sync_type_config_keys)(
                    schema.id, schema.team_id, updates=updates
                )
                schema.sync_type_config = {**(schema.sync_type_config or {}), **updates}

            await self.compact_if_fragmented(
                compact_small_files=compact_small_files,
                table_wide_small_files=compact_small_files
                and (decision.reason is not None or self._vacuumed_during_job(watermarks)),
            )
        except ObjectStorePermissionDeniedError:
            await self._logger.awarning("Delta maintenance skipped: the object store denied the operation")
            return
        except Exception as e:
            if is_transient_maintenance_error(e):
                await self._logger.awarning(f"Delta maintenance skipped: transient infra error: {e}")
                return
            capture_exception(e)
            await self._logger.aexception(f"Delta maintenance failed: {e}", exc_info=e)
