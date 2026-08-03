import json
import asyncio
from typing import TYPE_CHECKING

from django.conf import settings

import deltalake
import posthoganalytics

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async_pool
from posthog.utils import get_machine_id

from products.warehouse_sources.backend.models.external_data_schema import update_sync_type_config_keys
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.errors import (
    is_transient_maintenance_error,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.ops import (
    execute_with_conflict_retry,
)

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta_table_helper import (
        DeltaTableHelper,
    )

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


class DeltaMaintenance:
    """Compaction, vacuuming, and the vacuum-watermark cadence for one schema's Delta table.

    Stateless over a `DeltaTableHelper`, which holds the cached table handle — construct one at the
    call site whenever maintenance is needed. `run_scheduled` is the policy entry point shared by
    the pre-write defensive pass (both pipelines, so a sync that arrived at a fragmented table
    cleans up before adding to the pile) and the CDC post-load pass; `compact_table` is the
    unconditional post-load compaction for non-CDC syncs.
    """

    def __init__(self, table: "DeltaTableHelper") -> None:
        self._table = table
        self._logger = table.logger

    async def _vacuum(self, table: deltalake.DeltaTable) -> None:
        await self._logger.adebug("Vacuuming table...")
        vacuum_stats = await asyncio.to_thread(
            table.vacuum, retention_hours=24, enforce_retention_duration=False, dry_run=False
        )
        await self._logger.adebug(json.dumps(vacuum_stats))

    async def _compact(self, table: deltalake.DeltaTable) -> None:
        await self._logger.adebug("Compacting table...")
        compact_stats = await execute_with_conflict_retry(
            table, lambda: table.optimize.compact(), "compact_table", self._logger
        )
        await self._logger.adebug(json.dumps(compact_stats))

    async def compact_table(self) -> None:
        table = await self._table.get_delta_table()
        if table is None:
            raise Exception("Deltatable not found")

        await self._compact(table)
        # Reuse the table already resolved above instead of re-fetching it: `get_delta_table`
        # is cached only opportunistically, so a re-fetch here can race a concurrent sync of a
        # different table evicting this table's cache entry and spuriously report it missing.
        await self._vacuum(table)
        await self._logger.adebug("Compacting and vacuuming complete")

    async def vacuum_if_stale(self, last_vacuum_version: int | None, commit_threshold: int) -> int | None:
        """Vacuum tombstoned files once enough commits have accrued since the last vacuum.

        Decoupled from merge success (called pre-write) so a table that OOMs its merge every run still
        gets cleaned — the post-load compaction never runs for it, which is how tables reach ~99% dead
        files. Vacuum only deletes dead files (an S3 LIST + delete), so unlike `compact_table`'s
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
    ) -> bool:
        """Run compact + vacuum if the table is fragmented past either threshold.

        Fragmented = files-per-partition > `threshold` OR total files > `total_threshold`.
        The total-files backstop matters because delta enumerates every file's metadata
        during a merge even when partition pruning skips reading them, so merge planning
        time tracks total files — a high partition_count must not let a table accumulate
        tens of thousands of files while staying under the per-partition bar.

        When `partition_count` is None it is derived from the table's actual layout (the
        distinct file directories in the delta log, no extra I/O) — only md5 partitioning
        persists a count on the schema, so datetime/numerical-partitioned tables always
        arrive here with None.

        Returns True if compaction ran, False if it was skipped. Cheap when the table is
        healthy: one S3 LIST via `table.file_uris`. Intended for pre-write defensive cleanup
        so a sync that arrived at a fragmented state (e.g. an earlier attempt that failed
        before reaching post-load compaction) cleans up before adding to the pile.
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
    ) -> int | None:
        """Single threshold-maintenance step: compact if fragmented, else vacuum on commit cadence.

        The two triggers are orthogonal — fragmentation (active file count) vs. commit cadence (tombstone
        accrual) — but they share one outcome, the vacuum watermark. `compact_if_fragmented` already
        vacuums as part of compaction, so when it runs it supersedes the cadence vacuum (no double vacuum
        in one run) and the watermark advances to the post-compaction version. When nothing was fragmented,
        fall through to `vacuum_if_stale`. Returns the single delta version to persist as the new
        `last_vacuum_version` watermark, or None when nothing changed — `run_scheduled` persists it.
        """
        compacted = await self.compact_if_fragmented(partition_count=partition_count)
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
    ) -> None:
        """Best-effort threshold maintenance owning the vacuum-watermark lifecycle for `schema`.

        Reads the right watermark, runs `run_maintenance`, and persists the returned watermark via
        `update_sync_type_config_keys` (row-locked merge) — both call sites (the pre-write defensive
        pass and the CDC post-load pass) share this, so the watermark can't drift between them.

        One schema can back two delta tables (snapshot + `_cdc` companion) whose delta versions are
        unrelated numbers, so each table's vacuum cadence gets its own watermark key — sharing one
        would corrupt both cadences. The companion also ignores `schema.partition_count` (it
        describes the snapshot table); `compact_if_fragmented` derives the companion's count from
        its actual layout instead.

        Never raises: a maintenance failure must not block the sync, and the next scheduled pass
        retries the same idempotent cleanup. A transient infra error (see
        `is_transient_maintenance_error`) — an object-store hiccup, a racy concurrent-maintenance
        DeltaError, or an app-DB connection blip — is logged at warning instead of captured.
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
            )
            if new_version is not None and new_version != last_vacuum_version:
                await database_sync_to_async_pool(update_sync_type_config_keys)(
                    schema.id, schema.team_id, updates={watermark_key: new_version}
                )
        except Exception as e:
            if is_transient_maintenance_error(e):
                await self._logger.awarning(f"Delta maintenance skipped: transient infra error: {e}")
                return
            capture_exception(e)
            await self._logger.aexception(f"Delta maintenance failed: {e}", exc_info=e)
