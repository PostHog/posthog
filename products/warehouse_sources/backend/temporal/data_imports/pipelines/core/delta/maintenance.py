import json
import asyncio
import datetime as dt
from collections import defaultdict
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from django.conf import settings

import deltalake
import posthoganalytics
import deltalake.exceptions

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async_pool
from posthog.utils import get_machine_id

from products.warehouse_sources.backend.models.external_data_schema import update_sync_type_config_keys
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.errors import (
    is_offset_overflow_compaction_error,
    is_transient_maintenance_error,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.ops import (
    ObjectStorePermissionDeniedError,
    execute_with_conflict_retry,
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

# How long a tombstoned file survives before vacuum may delete it. Readers that pin an older
# table version must stay inside this window — see MAX_SNAPSHOT_ROLLBACK in the fan-out
# warehouse-parent reader, which derives its bound from this value.
VACUUM_RETENTION = dt.timedelta(hours=24)


def removable_file_count(file_sizes: Iterable[int]) -> int:
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
    small = [size for size in sizes if size < DEFAULT_COMPACT_TARGET_SIZE_BYTES // 2]
    runs = len(sizes) - len(small) + 1
    output_files = runs + 2 * sum(small) // DEFAULT_COMPACT_TARGET_SIZE_BYTES
    return max(0, len(small) - output_files)


@frozen
class _PartitionFileStats:
    size_bytes: int
    removable_files: int


def _partition_file_stats(table: deltalake.DeltaTable) -> list[_PartitionFileStats]:
    """Stats for each partition, read from the Delta log with no S3 request."""
    # Each partition value is one directory, and an unpartitioned table keeps its files at the root.
    sizes: defaultdict[str, list[int]] = defaultdict(list)
    for path, size in table._table.get_add_file_sizes().items():
        sizes[path.rpartition("/")[0]].append(size or 0)
    return [
        _PartitionFileStats(size_bytes=sum(partition_sizes), removable_files=removable_file_count(partition_sizes))
        for partition_sizes in sizes.values()
    ]


class DeltaMaintenance:
    """Compaction, vacuuming, and the vacuum-watermark cadence for one schema's Delta table.

    Stateless over a `DeltaTableRef`, which holds the cached table handle — construct one at the
    call site whenever maintenance is needed. `run_scheduled` is the policy entry point shared by
    the pre-write defensive pass (both pipelines, so a sync that arrived at a fragmented table
    cleans up before adding to the pile) and the post-load pass.
    """

    def __init__(self, table: "DeltaTableRef") -> None:
        self._table = table
        self._logger = table.logger

    async def _vacuum(self, table: deltalake.DeltaTable) -> None:
        await self._logger.adebug("Vacuuming table...")
        # vacuum() commits a REMOVE of tombstoned files, so it's just as subject to delta-rs's
        # conflict checker as merge/optimize.compact — see execute_with_conflict_retry.
        vacuum_stats = await execute_with_conflict_retry(
            table,
            lambda: table.vacuum(
                retention_hours=int(VACUUM_RETENTION.total_seconds() // 3600),
                enforce_retention_duration=False,
                dry_run=False,
            ),
            "vacuum_table",
            self._logger,
        )
        await self._logger.adebug(json.dumps(vacuum_stats))

    async def _compact(self, table: deltalake.DeltaTable) -> None:
        await self._logger.adebug("Compacting table...")
        target_size = DEFAULT_COMPACT_TARGET_SIZE_BYTES
        attempt = 0
        while True:

            def _compact_op(size: int = target_size) -> dict[str, Any]:
                return table.optimize.compact(target_size=size)

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
                await self._logger.awarning(
                    f"compact: byte array offset overflow, retrying with smaller "
                    f"target_size={target_size} (attempt {attempt}/{COMPACT_OFFSET_OVERFLOW_RETRIES})"
                )
        await self._logger.adebug(json.dumps(compact_stats))

    async def _vacuum_due(self, last_vacuum_version: int | None, commit_threshold: int) -> bool:
        # The same cadence `vacuum_if_stale` applies. An unseeded watermark is never due.
        table = await self._table.get_delta_table()
        if table is None or last_vacuum_version is None:
            return False
        return await asyncio.to_thread(table.version) - last_vacuum_version >= commit_threshold

    async def vacuum_if_stale(self, last_vacuum_version: int | None, commit_threshold: int) -> int | None:
        """Vacuum tombstoned files once enough commits have accrued since the last vacuum.

        Decoupled from merge success (called pre-write) so a table that OOMs its merge every run still
        gets cleaned — the post-load compaction never runs for it, which is how tables reach ~99% dead
        files. Vacuum only deletes dead files (an S3 LIST + delete), so unlike `compact_if_fragmented`'s
        `optimize.compact` (which rewrites partitions) it is memory-safe even on an oversized table.

        Uses the delta version (commit count) as a cheap proxy for tombstone accumulation — no S3 LIST to
        decide. Returns the current version to persist as the new watermark when it vacuumed, on first
        encounter, or when the table was recreated (both reseed the watermark without vacuuming);
        None when nothing changed.
        """
        table = await self._table.get_delta_table()
        if table is None:
            return None

        version = await asyncio.to_thread(table.version)
        if last_vacuum_version is None or version < last_vacuum_version:
            # First encounter: seed the watermark without vacuuming so existing tables clean up gradually
            # over the next `commit_threshold` commits rather than all vacuuming at once on deploy.
            # A version below the watermark means the table was reset/recreated (delta versions are
            # monotonic within one incarnation) and no reset path clears the persisted watermark —
            # left alone it would block the cadence until the new table out-versioned the old one.
            return version

        commits_since = version - last_vacuum_version
        if commits_since < commit_threshold:
            await self._logger.adebug(
                f"vacuum_if_stale: skipping, {commits_since} commits since last vacuum (< {commit_threshold})"
            )
            return None

        await self._logger.ainfo(
            f"vacuum_if_stale: {commits_since} commits since last vacuum (>= {commit_threshold}), vacuuming"
        )
        await self._vacuum(table)
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
                    "commits_since_last_vacuum": commits_since,
                    "delta_version": version,
                },
            )
        except Exception as e:
            capture_exception(e)
        return version

    async def compact_if_fragmented(
        self,
        partition_count: int | None,
        threshold: int = DEFAULT_COMPACT_FILES_PER_PARTITION_THRESHOLD,
        total_threshold: int = DEFAULT_COMPACT_TOTAL_FILES_THRESHOLD,
        compact_small_files: bool = False,
        table_wide_small_files: bool = False,
    ) -> bool:
        """Run compact + vacuum if the table is fragmented past either threshold.

        Fragmented = files-per-partition > `threshold` OR total files > `total_threshold`.
        The total-files backstop matters because delta enumerates every file's metadata
        during a merge even when partition pruning skips reading them, so merge planning
        time tracks total files — a high partition_count must not let a table accumulate
        tens of thousands of files while staying under the per-partition bar.

        `compact_small_files` adds the removable-file triggers (see
        `DEFAULT_COMPACT_REMOVABLE_FILES_PER_PARTITION_THRESHOLD`), plus a trigger for any
        partition over the repartition budget that compaction can shrink. Only the non-CDC
        post-load pass sets it. The pre-write pass is a backstop for a table that arrived
        fragmented, and a CDC final lands every tick, so these triggers would compact a CDC table
        every few ticks. `table_wide_small_files` also enables the table-wide removable-file
        trigger, which `run_maintenance` sets only when the vacuum is due.

        When `partition_count` is None it is derived from the table's actual layout (the
        distinct file directories in the delta log, no extra I/O) — only md5 partitioning
        persists a count on the schema, so datetime/numerical-partitioned tables always
        arrive here with None.

        Returns True if compaction ran, False if it was skipped. Cheap when the table is
        healthy: one S3 LIST via `table.file_uris`. Runs pre-write, so a sync that arrived at a
        fragmented state (e.g. an earlier attempt that failed before reaching post-load) cleans up
        before adding to the pile, and again post-load once the sync's own files have landed.
        """
        table = await self._table.get_delta_table()
        if table is None:
            return False

        file_uris = await asyncio.to_thread(table.file_uris)
        total_files = len(file_uris)
        if partition_count is None:
            # One directory per partition value; unpartitioned tables collapse to the single
            # table root. Without this, a partitioned table with no persisted count reads as
            # one giant partition and trips the per-partition threshold on every run.
            partition_count = len({uri.rsplit("/", 1)[0] for uri in file_uris})
        # Treat unpartitioned tables as one "partition" for the threshold math.
        effective_partitions = max(partition_count or 1, 1)
        files_per_partition = total_files / effective_partitions

        fragmented = files_per_partition > threshold or total_files > total_threshold
        stats = (
            f"total_files={total_files}, partitions={effective_partitions}, "
            f"files_per_partition={files_per_partition:.1f}, threshold={threshold}, "
            f"total_threshold={total_threshold}"
        )
        if compact_small_files and not fragmented:
            partitions = await asyncio.to_thread(_partition_file_stats, table)
            max_removable = max((partition.removable_files for partition in partitions), default=0)
            total_removable = sum(partition.removable_files for partition in partitions)
            # Repartition detection runs after this pass and compares partition bytes to its budget.
            # Small files take more bytes at rest than the same rows after compaction, so an
            # over-budget partition that compaction can shrink must be compacted before it is measured.
            budget = settings.DATA_WAREHOUSE_TARGET_PARTITION_BYTES
            compactable_over_budget = any(
                partition.size_bytes > budget and partition.removable_files > 0 for partition in partitions
            )
            fragmented = (
                max_removable >= DEFAULT_COMPACT_REMOVABLE_FILES_PER_PARTITION_THRESHOLD
                or (table_wide_small_files and total_removable >= DEFAULT_COMPACT_REMOVABLE_FILES_THRESHOLD)
                or compactable_over_budget
            )
            stats += (
                f", max_removable_files_per_partition={max_removable}, removable_files={total_removable}, "
                f"compactable_over_budget={compactable_over_budget}"
            )
        if not fragmented:
            await self._logger.adebug(f"compact_if_fragmented: skipping ({stats})")
            return False

        await self._logger.ainfo(f"compact_if_fragmented: triggering compact ({stats})")
        await self._compact(table)
        await self._vacuum(table)
        return True

    async def run_maintenance(
        self,
        partition_count: int | None,
        last_vacuum_version: int | None,
        commit_threshold: int,
        compact_small_files: bool = False,
    ) -> int | None:
        """Single threshold-maintenance step: compact if fragmented, else vacuum on commit cadence.

        The two triggers are orthogonal — fragmentation (active file count) vs. commit cadence (tombstone
        accrual) — but they share one outcome, the vacuum watermark. `compact_if_fragmented` already
        vacuums as part of compaction, so when it runs it supersedes the cadence vacuum (no double vacuum
        in one run) and the watermark advances to the post-compaction version. When nothing was fragmented,
        fall through to `vacuum_if_stale`. Returns the single delta version to persist as the new
        `last_vacuum_version` watermark, or None when nothing changed — `run_scheduled` persists it.
        """
        compacted = await self.compact_if_fragmented(
            partition_count=partition_count,
            compact_small_files=compact_small_files,
            table_wide_small_files=compact_small_files
            and await self._vacuum_due(last_vacuum_version, commit_threshold),
        )
        if compacted:
            table = await self._table.get_delta_table()
            if table is None:
                return None
            # Compaction (which vacuumed) added a commit, advancing the version; reset the cadence
            # watermark to it so the next vacuum is measured from this cleanup, not the old baseline.
            return await asyncio.to_thread(table.version)
        return await self.vacuum_if_stale(last_vacuum_version, commit_threshold)

    async def run_scheduled(
        self,
        schema: "ExternalDataSchema",
        *,
        is_cdc_companion: bool = False,
        partition_count_fallback: int | None = None,
        compact_small_files: bool = False,
    ) -> None:
        """Best-effort threshold maintenance owning the vacuum-watermark lifecycle for `schema`.

        Reads the right watermark, runs `run_maintenance`, and persists the returned watermark via
        `update_sync_type_config_keys` (row-locked merge) — both call sites (the pre-write defensive
        pass and the post-load pass) share this, so the watermark can't drift between them.

        One schema can back two delta tables (snapshot + `_cdc` companion) whose delta versions are
        unrelated numbers, so each table's vacuum cadence gets its own watermark key — sharing one
        would corrupt both cadences. The companion also ignores `schema.partition_count` (it
        describes the snapshot table); `compact_if_fragmented` derives the companion's count from
        its actual layout instead.

        Never raises: a maintenance failure must not block the sync, and the next scheduled pass
        retries the same idempotent cleanup. A transient infra error (see
        `is_transient_maintenance_error`) — an object-store hiccup, a racy concurrent-maintenance
        DeltaError, or an app-DB connection blip — is logged at warning instead of captured.

        An object-store refusal (see is_object_store_permission_denied) is logged at warning too.
        Compaction and vacuuming only rewrite and reclaim files that the load has already committed,
        so a refused pass leaves every live row queryable and costs the table nothing but a delayed
        cleanup. It is a policy condition on our own bucket rather than a maintenance defect, so a
        report per sync would say the same thing repeatedly about something no code change fixes.
        The watermark is not persisted either, so the cadence re-attempts the vacuum on the next pass
        instead of waiting another `commit_threshold` commits for a cleanup that never ran.
        """
        try:
            if is_cdc_companion:
                partition_count = None
                watermark_key = "last_vacuum_version_cdc"
                last_vacuum_version = schema.last_vacuum_version_cdc
            else:
                partition_count = schema.partition_count or partition_count_fallback
                watermark_key = "last_vacuum_version"
                last_vacuum_version = schema.last_vacuum_version

            new_version = await self.run_maintenance(
                partition_count=partition_count,
                last_vacuum_version=last_vacuum_version,
                commit_threshold=settings.DATA_WAREHOUSE_VACUUM_COMMIT_THRESHOLD,
                compact_small_files=compact_small_files,
            )
            if new_version is not None and new_version != last_vacuum_version:
                await database_sync_to_async_pool(update_sync_type_config_keys)(
                    schema.id, schema.team_id, updates={watermark_key: new_version}
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
