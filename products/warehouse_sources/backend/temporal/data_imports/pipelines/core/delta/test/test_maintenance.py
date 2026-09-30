import os
import tempfile

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import override_settings

import pyarrow as pa
import deltalake
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.maintenance import (
    COMPACT_OFFSET_OVERFLOW_RETRIES,
    DeltaMaintenance,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.ops import (
    ObjectStorePermissionDeniedError,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.test.helpers import make_logger

_MAINTENANCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.maintenance"
_MB = 1024 * 1024
# Small enough that a local table can hold files above the compaction target.
_SMALL_TARGET = 100_000


def _append_file(path: str, row_id: int, payload_bytes: int) -> None:
    # Random hex keeps each file about as large as its payload, because parquet cannot compress it much.
    blob = os.urandom(payload_bytes).hex()[:payload_bytes]
    deltalake.write_deltalake(path, pa.table({"id": [row_id], "blob": [blob]}), mode="append")


def _make_maintenance(delta_table: deltalake.DeltaTable | MagicMock | None) -> DeltaMaintenance:
    table_ref = MagicMock()
    table_ref.logger = make_logger()
    table_ref.get_delta_table = AsyncMock(return_value=delta_table)
    return DeltaMaintenance(table_ref)


def _passthrough_pool(fn):
    async def _call(*args, **kwargs):
        return fn(*args, **kwargs)

    return _call


class TestCompactIfFragmented:
    """Defensive compaction fires on files-per-partition OR total-files threshold."""

    @pytest.mark.asyncio
    async def test_skips_when_no_delta_table(self):
        ran = await _make_maintenance(None).compact_if_fragmented(partition_count=10)
        assert ran is False

    # (case_name, file_count, partition_count, threshold_kw, expected_ran)
    # threshold_kw=None means "use default threshold" — exercises the prod path.
    _THRESHOLD_CASES: list[tuple[str, int, int | None, int | None, bool]] = [
        # 100 / 10 = 10 fpp, well below default 200 -> skip
        ("below_default_threshold", 100, 10, None, False),
        # 5,000 / 10 = 500 fpp, well above default 200 -> fire
        ("above_default_threshold", 5_000, 10, None, True),
        # partition_count=None on an unpartitioned layout derives 1 partition; 250 fpp >> 200 -> fire
        ("unpartitioned_above_default", 250, None, None, True),
        # Custom threshold: 100 / 10 = 10 fpp, threshold=5 -> fire
        ("custom_threshold_fires", 100, 10, 5, True),
        # Boundary: exactly at threshold -> `>` not `>=`, so skip
        ("exactly_at_default_threshold", 2_000, 10, None, False),
        # Total-files backstop: 6,000 / 100 = 60 fpp (under the per-partition bar) but
        # total 6,000 > 5,000 default total threshold -> fire. Guards high-partition tables.
        ("total_cap_fires_under_per_partition", 6_000, 100, None, True),
        # Under both bars: 4,000 / 100 = 40 fpp and total 4,000 < 5,000 -> skip.
        ("below_both_thresholds", 4_000, 100, None, False),
    ]

    @parameterized.expand(_THRESHOLD_CASES)
    @pytest.mark.asyncio
    async def test_threshold(
        self,
        _name: str,
        file_count: int,
        partition_count: int | None,
        threshold_kw: int | None,
        expected_ran: bool,
    ):
        file_uris = [f"s3://bucket/table/f{i}.parquet" for i in range(file_count)]
        mock_delta = MagicMock()
        mock_delta.file_uris = MagicMock(return_value=file_uris)
        maintenance = _make_maintenance(mock_delta)
        with (
            patch.object(maintenance, "_compact", AsyncMock()) as mock_compact,
            patch.object(maintenance, "_vacuum", AsyncMock()) as mock_vacuum,
        ):
            kwargs: dict = {"partition_count": partition_count}
            if threshold_kw is not None:
                kwargs["threshold"] = threshold_kw
            ran = await maintenance.compact_if_fragmented(**kwargs)

        assert ran is expected_ran
        if expected_ran:
            mock_compact.assert_called_once_with(mock_delta)
            mock_vacuum.assert_called_once_with(mock_delta)
        else:
            mock_compact.assert_not_called()
            mock_vacuum.assert_not_called()

    # (case_name, files_per_dir, dir_count, expected_ran)
    _DERIVATION_CASES: list[tuple[str, int, int, bool]] = [
        # 300 files / 3 derived partitions = 100 fpp < 200 and total < 5,000 -> skip.
        # Before derivation, None meant 1 partition (300 fpp) and this healthy table
        # compacted on every run.
        ("healthy_partitioned_table_skips", 100, 3, False),
        # Genuinely fragmented per partition: 750/3 = 250 fpp > 200 -> still fires.
        ("fragmented_partitioned_table_fires", 250, 3, True),
    ]

    @parameterized.expand(_DERIVATION_CASES)
    @pytest.mark.asyncio
    async def test_partition_count_derived_from_layout(
        self, _name: str, files_per_dir: int, dir_count: int, expected_ran: bool
    ):
        # Only md5 partitioning persists a partition_count; datetime/numerical schemas pass
        # None. The count must come from the layout or every >200-file partitioned table
        # would defensively compact at the start of every sync run.
        file_uris = [
            f"s3://bucket/table/_ph_partition_key={d}/f{i}.parquet"
            for d in range(dir_count)
            for i in range(files_per_dir)
        ]
        mock_delta = MagicMock()
        mock_delta.file_uris = MagicMock(return_value=file_uris)
        maintenance = _make_maintenance(mock_delta)
        with (
            patch.object(maintenance, "_compact", AsyncMock()) as mock_compact,
            patch.object(maintenance, "_vacuum", AsyncMock()) as mock_vacuum,
        ):
            ran = await maintenance.compact_if_fragmented(partition_count=None)

        assert ran is expected_ran
        if expected_ran:
            mock_compact.assert_called_once_with(mock_delta)
            mock_vacuum.assert_called_once_with(mock_delta)
        else:
            mock_compact.assert_not_called()
            mock_vacuum.assert_not_called()

    # (case_name, layout as [(partitions, file sizes in each)], compact_small_files, table_wide_small_files,
    # expected_ran)
    _SMALL_FILE_CASES: list[tuple[str, list[tuple[int, list[int]]], bool, bool, bool]] = [
        # An incremental datetime table: every sync lands in the newest partition, and 600 cold
        # partitions hold the average near one file per partition, so the averages never fire.
        ("hot_partition_fires", [(600, [60 * _MB]), (1, [_MB] * 9)], True, False, True),
        # The pre-write pass and CDC tables keep the average-only thresholds.
        ("hot_partition_ignored_without_small_file_triggers", [(600, [60 * _MB]), (1, [_MB] * 9)], False, False, False),
        ("hot_partition_below_threshold_skips", [(600, [60 * _MB]), (1, [_MB] * 8)], True, False, False),
        # Compaction writes files between half and the whole target, and delta-rs cannot pair two of
        # them into one bin. Counting them would start a compaction that does nothing on every sync.
        ("compaction_output_never_counts", [(600, [60 * _MB]), (1, [60 * _MB] * 20)], True, True, False),
        # A cold tail of partitions with a few small files each, which no single partition reveals.
        ("cold_tail_fires", [(100, [_MB] * 2)], True, True, True),
        ("cold_tail_below_threshold_skips", [(99, [_MB] * 2)], True, True, False),
        # md5 hashes new rows into every bucket, so each sync adds a small file to each one. Checked on
        # every sync, the table-wide count would compact the whole table every time.
        ("every_partition_grows_waits_for_table_wide_check", [(150, [20 * _MB, _MB])], True, False, False),
        # Repartition detection measures right after this pass, so a partition that its small files
        # push over the budget must compact even below the removable thresholds, or it gets split.
        ("over_budget_partition_fires", [(1, [90 * _MB] * 6 + [_MB] * 10)], True, False, True),
        ("same_files_under_budget_skip", [(1, [90 * _MB] * 4 + [_MB] * 10)], True, False, False),
    ]

    @parameterized.expand(_SMALL_FILE_CASES)
    @pytest.mark.asyncio
    async def test_small_file_threshold(
        self,
        _name: str,
        layout: list[tuple[int, list[int]]],
        compact_small_files: bool,
        table_wide_small_files: bool,
        expected_ran: bool,
    ):
        file_sizes = {
            f"_ph_partition_key={group}-{partition}/f{i}.parquet": size
            for group, (partitions, sizes) in enumerate(layout)
            for partition in range(partitions)
            for i, size in enumerate(sizes)
        }
        mock_delta = MagicMock()
        mock_delta.file_uris = MagicMock(return_value=[f"s3://bucket/table/{path}" for path in file_sizes])
        mock_delta._table.get_add_file_sizes = MagicMock(return_value=file_sizes)
        maintenance = _make_maintenance(mock_delta)
        with (
            override_settings(DATA_WAREHOUSE_TARGET_PARTITION_BYTES=500 * _MB),
            patch.object(maintenance, "_compact", AsyncMock()) as mock_compact,
            patch.object(maintenance, "_vacuum", AsyncMock()),
        ):
            ran = await maintenance.compact_if_fragmented(
                partition_count=None,
                compact_small_files=compact_small_files,
                table_wide_small_files=table_wide_small_files,
            )

        assert ran is expected_ran
        assert mock_compact.await_count == (1 if expected_ran else 0)

    @parameterized.expand(
        [
            ("adjacent_small_files_compact", False, True),
            # delta-rs merges only neighbouring files, and a file over the target splits them. A trigger
            # that counted these small files would start a compaction that removes nothing on every sync.
            ("small_files_between_oversized_files_skip", True, False),
        ]
    )
    @pytest.mark.asyncio
    async def test_small_file_trigger_on_a_real_table(self, _name: str, interleave_oversized: bool, expected_ran: bool):
        with (
            tempfile.TemporaryDirectory() as path,
            patch(f"{_MAINTENANCE_MODULE}.DEFAULT_COMPACT_TARGET_SIZE_BYTES", _SMALL_TARGET),
        ):
            for i in range(12):
                _append_file(path, i, payload_bytes=500)
                if interleave_oversized:
                    _append_file(path, 100 + i, payload_bytes=2 * _SMALL_TARGET)
            table = deltalake.DeltaTable(path)
            files_before = len(table.file_uris())
            rows_before = table.to_pyarrow_table().num_rows

            ran = await _make_maintenance(table).compact_if_fragmented(partition_count=None, compact_small_files=True)

            assert ran is expected_ran
            files_after = len(table.file_uris())
            assert (files_after < files_before) is expected_ran
            assert table.to_pyarrow_table().num_rows == rows_before


class TestCompactConflictRetry:
    @pytest.mark.asyncio
    async def test_retries_compact_on_commit_conflict_then_succeeds(self):
        # optimize.compact() commits a REMOVE+ADD when rewriting fragmented files — the same
        # commit-conflict shape as a merge (see test_ops.TestExecuteWithConflictRetry). Regression
        # coverage for a CommitFailedError propagating straight out on the first conflict instead of
        # retrying with a refreshed table, like the write merges do.
        mock_delta = MagicMock()
        mock_delta.file_uris = MagicMock(return_value=[f"s3://t/{i}.parquet" for i in range(3)])
        mock_delta.optimize.compact = MagicMock(
            side_effect=[
                deltalake.exceptions.CommitFailedError(
                    "Commit failed: a concurrent transaction deleted data this operation read."
                ),
                {"numFilesAdded": 1},
            ]
        )
        mock_delta.vacuum = MagicMock(return_value=[])

        compacted = await _make_maintenance(mock_delta).compact_if_fragmented(partition_count=1, threshold=1)

        assert compacted is True
        assert mock_delta.optimize.compact.call_count == 2
        mock_delta.update_incremental.assert_called_once()


class TestCompactOffsetOverflow:
    """Regression coverage for the byte-array-offset-overflow panic (delta-rs binning several
    already-safe files into one rewrite whose combined text column crosses the 32-bit offset
    limit — see errors.is_offset_overflow_compaction_error)."""

    @pytest.mark.asyncio
    async def test_retries_with_smaller_target_size_then_succeeds(self):
        mock_delta = MagicMock()
        mock_delta.optimize.compact = MagicMock(
            side_effect=[
                deltalake.exceptions.DeltaError(
                    'Generic error: task 1237385 panicked with message "byte array offset overflow"'
                ),
                {"numFilesAdded": 1},
            ]
        )
        mock_delta.vacuum = MagicMock(return_value=[])

        await _make_maintenance(mock_delta)._compact(mock_delta)

        assert mock_delta.optimize.compact.call_count == 2
        first_target_size = mock_delta.optimize.compact.call_args_list[0].kwargs["target_size"]
        second_target_size = mock_delta.optimize.compact.call_args_list[1].kwargs["target_size"]
        assert second_target_size == first_target_size // 2

    @pytest.mark.asyncio
    async def test_gives_up_after_exhausting_retries(self):
        # A table whose overflow can't be avoided at any reasonable bin size must still surface to
        # error tracking instead of looping the retry ladder forever.
        overflow_error = deltalake.exceptions.DeltaError(
            'Generic error: task 42 panicked with message "byte array offset overflow"'
        )
        mock_delta = MagicMock()
        mock_delta.optimize.compact = MagicMock(side_effect=overflow_error)

        with pytest.raises(deltalake.exceptions.DeltaError):
            await _make_maintenance(mock_delta)._compact(mock_delta)

        assert mock_delta.optimize.compact.call_count == COMPACT_OFFSET_OVERFLOW_RETRIES + 1

    @pytest.mark.asyncio
    async def test_unrelated_delta_error_is_not_retried(self):
        mock_delta = MagicMock()
        mock_delta.optimize.compact = MagicMock(side_effect=deltalake.exceptions.DeltaError("no protocol found"))

        with pytest.raises(deltalake.exceptions.DeltaError):
            await _make_maintenance(mock_delta)._compact(mock_delta)

        mock_delta.optimize.compact.assert_called_once()


class TestVacuum:
    @pytest.mark.asyncio
    async def test_retries_on_commit_conflict_then_succeeds(self):
        # vacuum() commits a REMOVE of tombstoned files — the same commit-conflict shape as
        # optimize.compact() (see TestCompactConflictRetry.test_retries_compact_on_commit_conflict_then_succeeds).
        # Regression coverage for a CommitFailedError propagating straight out of _vacuum on the first
        # conflict instead of retrying with a refreshed table, like _compact already does.
        mock_delta = MagicMock()
        mock_delta.vacuum = MagicMock(
            side_effect=[
                deltalake.exceptions.CommitFailedError(
                    "Commit failed: a concurrent transaction deleted data this operation read."
                ),
                [],
            ]
        )

        await _make_maintenance(mock_delta)._vacuum(mock_delta)

        assert mock_delta.vacuum.call_count == 2
        mock_delta.update_incremental.assert_called_once()


class TestVacuumIfStale:
    @parameterized.expand(
        [
            # (last_vacuum_version, expect_vacuum, expected_return) — current version=150, threshold=100.
            # First encounter must seed the watermark WITHOUT vacuuming (else every existing table vacuums
            # at once on deploy); below threshold must skip (else vacuum runs every sync); at/above threshold
            # must vacuum (else tombstones accumulate forever on tables that never reach post-load compaction).
            ("first_encounter_seeds_no_vacuum", None, False, 150),
            ("below_threshold_skips", 100, False, None),
            ("at_threshold_vacuums", 50, True, 150),
            ("above_threshold_vacuums", 40, True, 150),
            # A watermark above the current version means the table was reset/recreated (delta
            # versions are monotonic within one incarnation) and no reset path clears the persisted
            # watermark — it must reseed, not block the cadence until the version catches up.
            ("stale_watermark_from_recreated_table_reseeds", 999, False, 150),
        ]
    )
    @pytest.mark.asyncio
    async def test_vacuum_cadence(
        self, _name: str, last_version: int | None, expect_vacuum: bool, expected_return: int | None
    ):
        table = MagicMock()
        table.version = MagicMock(return_value=150)
        maintenance = _make_maintenance(table)
        with (
            patch.object(maintenance, "_vacuum", new=AsyncMock()) as vacuum,
            patch(f"{_MAINTENANCE_MODULE}.posthoganalytics") as ph,
        ):
            result = await maintenance.vacuum_if_stale(last_version, 100)

        assert result == expected_return
        assert vacuum.await_count == (1 if expect_vacuum else 0)
        if expect_vacuum:
            vacuum.assert_awaited_once_with(table)
        # The observability event fires exactly when a vacuum runs — not on seed/skip — so the cadence is measurable.
        assert ph.capture.call_count == (1 if expect_vacuum else 0)
        if expect_vacuum:
            assert ph.capture.call_args.kwargs["event"] == "warehouse_delta_vacuumed"


class TestRunMaintenance:
    """run_maintenance is the single threshold-maintenance step: compaction supersedes the cadence vacuum."""

    @pytest.mark.asyncio
    async def test_compaction_supersedes_vacuum_and_advances_watermark(self):
        # Fragmented table: compact runs (and vacuums as part of it), so the cadence vacuum is skipped —
        # no double vacuum in one run — and the watermark advances to the post-compaction version.
        table = MagicMock(version=MagicMock(return_value=200))
        maintenance = _make_maintenance(table)
        with (
            patch.object(maintenance, "compact_if_fragmented", new=AsyncMock(return_value=True)),
            patch.object(maintenance, "vacuum_if_stale", new=AsyncMock()) as vacuum_if_stale,
        ):
            result = await maintenance.run_maintenance(partition_count=10, last_vacuum_version=50, commit_threshold=100)

        assert result == 200
        vacuum_if_stale.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_falls_through_to_vacuum_when_not_fragmented(self):
        # Not fragmented → no compaction; fall through to the commit-cadence vacuum and return its watermark.
        maintenance = _make_maintenance(MagicMock())
        with (
            patch.object(maintenance, "compact_if_fragmented", new=AsyncMock(return_value=False)),
            patch.object(maintenance, "vacuum_if_stale", new=AsyncMock(return_value=150)) as vacuum_if_stale,
        ):
            result = await maintenance.run_maintenance(partition_count=10, last_vacuum_version=40, commit_threshold=100)

        assert result == 150
        vacuum_if_stale.assert_awaited_once_with(40, 100)

    @parameterized.expand(
        [
            # (name, compact_small_files, last_vacuum_version, expected_table_wide) at version 200 with a
            # 100-commit cadence. 150 commits since the last vacuum is due, 50 is not, and a watermark that
            # was never seeded is never due.
            ("vacuum_due", True, 50, True),
            ("vacuum_not_due", True, 150, False),
            ("watermark_not_seeded", True, None, False),
            ("small_file_triggers_off", False, 50, False),
        ]
    )
    @pytest.mark.asyncio
    async def test_table_wide_small_file_trigger_follows_the_vacuum_cadence(
        self, _name: str, compact_small_files: bool, last_vacuum_version: int | None, expected_table_wide: bool
    ):
        maintenance = _make_maintenance(MagicMock(version=MagicMock(return_value=200)))
        with (
            patch.object(maintenance, "compact_if_fragmented", new=AsyncMock(return_value=False)) as compact,
            patch.object(maintenance, "vacuum_if_stale", new=AsyncMock(return_value=None)),
        ):
            await maintenance.run_maintenance(
                partition_count=10,
                last_vacuum_version=last_vacuum_version,
                commit_threshold=100,
                compact_small_files=compact_small_files,
            )

        assert compact.await_args is not None
        assert compact.await_args.kwargs["compact_small_files"] is compact_small_files
        assert compact.await_args.kwargs["table_wide_small_files"] is expected_table_wide


class TestRunScheduled:
    """run_scheduled owns the vacuum-watermark lifecycle for both call sites (pre-write defensive
    pass and post-load), so watermark-key selection, persistence gating, and the never-raise
    contract all live here."""

    def _schema(self) -> MagicMock:
        schema = MagicMock()
        schema.partition_count = 10
        schema.last_vacuum_version = 41
        schema.last_vacuum_version_cdc = 7
        return schema

    async def _run(
        self,
        maintenance: DeltaMaintenance,
        schema: MagicMock,
        *,
        run_maintenance_result: int | None | Exception = None,
        is_cdc_companion: bool = False,
        partition_count_fallback: int | None = None,
        compact_small_files: bool = False,
    ) -> tuple[AsyncMock, MagicMock, MagicMock]:
        run_maintenance = (
            AsyncMock(side_effect=run_maintenance_result)
            if isinstance(run_maintenance_result, Exception)
            else AsyncMock(return_value=run_maintenance_result)
        )
        with (
            patch.object(maintenance, "run_maintenance", run_maintenance),
            patch(f"{_MAINTENANCE_MODULE}.database_sync_to_async_pool", _passthrough_pool),
            patch(f"{_MAINTENANCE_MODULE}.update_sync_type_config_keys") as update_config,
            patch(f"{_MAINTENANCE_MODULE}.capture_exception") as capture,
        ):
            await maintenance.run_scheduled(
                schema,
                is_cdc_companion=is_cdc_companion,
                partition_count_fallback=partition_count_fallback,
                compact_small_files=compact_small_files,
            )
        return run_maintenance, update_config, capture

    @parameterized.expand([("on", True), ("off", False)])
    @pytest.mark.asyncio
    async def test_forwards_small_file_triggers(self, _name: str, compact_small_files: bool):
        # Only the non-CDC post-load pass turns these triggers on, so a dropped pass-through here turns
        # them off for every table while every caller-side test stays green.
        run_maintenance, _, _ = await self._run(
            _make_maintenance(MagicMock()), self._schema(), compact_small_files=compact_small_files
        )

        assert run_maintenance.await_args is not None
        assert run_maintenance.await_args.kwargs["compact_small_files"] is compact_small_files

    @parameterized.expand(
        [
            # (name, is_cdc_companion, schema_partition_count, fallback, expected_count, expected_last, expected_key)
            # The schema's persisted count wins over the source's fallback.
            ("main_schema_count_wins", False, 10, 72, 10, 41, "last_vacuum_version"),
            # md5-less schemas persist no count; the source-provided fallback applies.
            ("main_falls_back_to_source_count", False, None, 72, 72, 41, "last_vacuum_version"),
            ("main_both_none_derives_downstream", False, None, None, None, 41, "last_vacuum_version"),
            # The snapshot and _cdc companion are different delta tables with unrelated versions, so
            # the companion must use last_vacuum_version_cdc — sharing a key corrupts both cadences —
            # and must ignore schema.partition_count, which describes the snapshot table's layout.
            ("companion_own_key_and_layout", True, 10, 72, None, 7, "last_vacuum_version_cdc"),
        ]
    )
    @pytest.mark.asyncio
    async def test_partition_count_and_watermark_key_selection(
        self,
        _name: str,
        is_cdc_companion: bool,
        schema_count: int | None,
        fallback: int | None,
        expected_count: int | None,
        expected_last: int,
        expected_key: str,
    ):
        schema = self._schema()
        schema.partition_count = schema_count
        run_maintenance, update_config, _ = await self._run(
            _make_maintenance(MagicMock()),
            schema,
            run_maintenance_result=99,
            is_cdc_companion=is_cdc_companion,
            partition_count_fallback=fallback,
        )

        assert run_maintenance.await_args is not None
        assert run_maintenance.await_args.kwargs["partition_count"] == expected_count
        assert run_maintenance.await_args.kwargs["last_vacuum_version"] == expected_last
        update_config.assert_called_once_with(schema.id, schema.team_id, updates={expected_key: 99})

    @parameterized.expand(
        [
            # run_maintenance returning a version must persist it — a lost watermark means
            # vacuum_if_stale re-seeds forever and the table never vacuums.
            ("new_version_persists", 55, True),
            ("no_change_skips_write", None, False),
            ("same_version_skips_write", 41, False),
        ]
    )
    @pytest.mark.asyncio
    async def test_watermark_persistence_gating(self, _name: str, returned_version: int | None, expect_write: bool):
        schema = self._schema()
        _, update_config, _ = await self._run(
            _make_maintenance(MagicMock()), schema, run_maintenance_result=returned_version
        )

        if expect_write:
            update_config.assert_called_once_with(
                schema.id, schema.team_id, updates={"last_vacuum_version": returned_version}
            )
        else:
            update_config.assert_not_called()

    @parameterized.expand(
        [
            # A genuine maintenance bug must be captured for visibility but never raise — the sync
            # itself must proceed either way. The full transient-vs-genuine classification matrix
            # lives in test_errors.py; this covers the two handling paths.
            ("genuine_bug_captured", RuntimeError("maintenance blew up"), True),
            # A transient infra blip self-heals on the next scheduled pass and must not be promoted
            # into a fresh error-tracking issue.
            ("transient_blip_warned_only", OSError("Generic S3 error: Please reduce your request rate."), False),
            # A commit conflict that exhausted execute_with_conflict_retry's budget (sustained
            # contention from another still-running maintenance pass) is the same self-healing race,
            # just losing at commit time instead of during compact's file scan.
            (
                "commit_conflict_retries_exhausted_warned_only",
                deltalake.exceptions.CommitFailedError(
                    "Commit failed: a concurrent transaction deleted data this operation read."
                ),
                False,
            ),
            # A refused read/write/delete on our own bucket is a policy condition rather than a
            # maintenance defect, and no code change fixes it, so reporting it once per sync says
            # the same thing repeatedly. The watermark assertion below is what keeps the cadence
            # re-attempting the vacuum instead of waiting another commit_threshold commits for a
            # cleanup that never ran.
            ("object_store_refusal_warned_only", ObjectStorePermissionDeniedError("denied"), False),
        ]
    )
    @pytest.mark.asyncio
    async def test_never_raises(self, _name: str, error: Exception, expect_capture: bool):
        logger = make_logger()
        table_ref = MagicMock()
        table_ref.logger = logger
        table_ref.get_delta_table = AsyncMock(return_value=MagicMock())
        maintenance = DeltaMaintenance(table_ref)

        _, update_config, capture = await self._run(maintenance, self._schema(), run_maintenance_result=error)

        assert capture.called is expect_capture
        update_config.assert_not_called()
        if expect_capture:
            logger.aexception.assert_awaited_once()
        else:
            logger.awarning.assert_awaited_once()
