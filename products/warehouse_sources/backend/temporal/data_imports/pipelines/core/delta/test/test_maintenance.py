import os
import json
import time
import datetime as dt
import tempfile
from pathlib import Path
from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.conf import settings
from django.test import override_settings

import pyarrow as pa
import deltalake
import deltalite
import pyarrow.parquet as pq
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.deltalite_handles import (
    DeltaLiteHandleCache,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.errors import (
    TransientObjectStoreError,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.maintenance import (
    _COMPACT_RATIO_SAMPLE_FILES,
    COMPACT_OFFSET_OVERFLOW_RETRIES,
    DEFAULT_COMPACT_TARGET_SIZE_BYTES,
    DELTA_DELETED_FILE_RETENTION,
    VACUUM_RETENTION,
    CompactionPlan,
    DeltaMaintenance,
    VacuumCadence,
    VacuumWatermarks,
    _sample_compression_ratio,
    decide_vacuum,
    plan_compaction,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.ops import (
    ObjectStorePermissionDeniedError,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.test.helpers import make_logger

_MAINTENANCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.maintenance"
_MB = 1024 * 1024
# Small enough that a local table can hold files above the compaction target.
_SMALL_TARGET = 100_000
_NOW = dt.datetime(2026, 6, 1, 12, 0, tzinfo=dt.UTC)
_DEFAULT_PLAN = CompactionPlan(
    target_size=DEFAULT_COMPACT_TARGET_SIZE_BYTES, max_concurrent_tasks=1, compression_ratio=1.0, slot_budget_mb=1356.8
)
_CADENCE = VacuumCadence(commit_threshold=100, max_interval=dt.timedelta(days=5), full_interval=dt.timedelta(days=7))


def _append_file(path: str, row_id: int, payload_bytes: int) -> None:
    # Random hex keeps each file about as large as its payload, because parquet cannot compress it much.
    blob = os.urandom(payload_bytes).hex()[:payload_bytes]
    deltalake.write_deltalake(path, pa.table({"id": [row_id], "blob": [blob]}), mode="append")


def _make_maintenance(
    delta_table: deltalake.DeltaTable | MagicMock | None, *, now: dt.datetime = _NOW
) -> DeltaMaintenance:
    table_ref = MagicMock()
    table_ref.logger = make_logger()
    table_ref.get_delta_table = AsyncMock(return_value=delta_table)
    table_ref.job.created_at = now - dt.timedelta(minutes=30)
    return DeltaMaintenance(table_ref, clock=lambda: now)


def _mock_table(file_sizes: dict[str, int], version: int = 150) -> MagicMock:
    table = MagicMock()
    table.file_uris = MagicMock(return_value=[f"s3://bucket/table/{path}" for path in file_sizes])
    table._table.get_add_file_sizes = MagicMock(return_value=file_sizes)
    table.version = MagicMock(return_value=version)
    return table


def _layout(groups: list[tuple[int, list[int]]]) -> dict[str, int]:
    return {
        f"_ph_partition_key={group}-{partition}/f{i}.parquet": size
        for group, (partitions, sizes) in enumerate(groups)
        for partition in range(partitions)
        for i, size in enumerate(sizes)
    }


def _passthrough_pool(fn):
    async def _call(*args, **kwargs):
        return fn(*args, **kwargs)

    return _call


def _parquet_files(root: str) -> set[str]:
    return {str(path.relative_to(root)) for path in Path(root).rglob("*.parquet") if "_delta_log" not in path.parts}


def _dead_files(root: str) -> set[str]:
    live = set(deltalake.DeltaTable(root)._table.get_add_file_sizes())
    return _parquet_files(root) - live


class TestCompactIfFragmented:
    @pytest.mark.asyncio
    async def test_skips_when_no_delta_table(self):
        ran = await _make_maintenance(None).compact_if_fragmented()
        assert ran is False

    # (case_name, file_count, partition directories or None for unpartitioned, threshold_kw,
    # expected_ran). Every file is small, so a count trigger can always remove files here.
    _THRESHOLD_CASES: list[tuple[str, int, int | None, int | None, bool]] = [
        ("below_default_threshold", 100, 10, None, False),
        ("above_default_threshold", 5_000, 10, None, True),
        # An unpartitioned layout is one partition: 250 fpp >> 200 -> fire
        ("unpartitioned_above_default", 250, None, None, True),
        ("custom_threshold_fires", 100, 10, 5, True),
        # Boundary: exactly at threshold -> `>` not `>=`, so skip
        ("exactly_at_default_threshold", 2_000, 10, None, False),
        # Total-files backstop: 60 fpp is under the per-partition bar, but 6,000 files is over 5,000.
        ("total_cap_fires_under_per_partition", 6_000, 100, None, True),
        ("below_both_thresholds", 4_000, 100, None, False),
    ]

    @parameterized.expand(_THRESHOLD_CASES)
    @pytest.mark.asyncio
    async def test_threshold(
        self,
        _name: str,
        file_count: int,
        partitions: int | None,
        threshold_kw: int | None,
        expected_ran: bool,
    ):
        layout = (
            {f"f{i}.parquet": _MB for i in range(file_count)}
            if partitions is None
            else _layout([(partitions, [_MB] * (file_count // partitions))])
        )
        mock_delta = _mock_table(layout)
        maintenance = _make_maintenance(mock_delta)
        with (
            patch.object(maintenance, "_plan_compaction", AsyncMock(return_value=_DEFAULT_PLAN)),
            patch.object(maintenance, "_compact", AsyncMock(return_value=True)) as mock_compact,
            patch.object(maintenance, "_vacuum", AsyncMock()) as mock_vacuum,
        ):
            kwargs: dict = {}
            if threshold_kw is not None:
                kwargs["threshold"] = threshold_kw
            ran = await maintenance.compact_if_fragmented(**kwargs)

        assert ran is expected_ran
        assert mock_compact.await_count == (1 if expected_ran else 0)
        # Compaction tombstones are younger than the vacuum retention, so a vacuum right after it is wasted.
        mock_vacuum.assert_not_called()

    # (case_name, file layout, expected_ran)
    _COUNT_TRIGGER_CASES: list[tuple[str, list[tuple[int, list[int]]], bool]] = [
        # An hourly-partitioned table: one file in each of 13,215 partitions, and a few partitions
        # with a second file. It stays over the total-files bar after any compaction, so a count
        # trigger that ignores removable files compacts and commits on every pass.
        ("one_file_per_partition_never_compacts", [(13_215, [300_000]), (6, [300_000, 300_000])], False),
        # The same table once many partitions hold a second small file: compaction removes thousands.
        ("many_partitions_with_two_small_files_compacts", [(6_000, [300_000, 300_000])], True),
        # One partition far over the per-partition bar, with files compaction cannot merge.
        ("over_per_partition_bar_with_large_files_skips", [(1, [60 * _MB] * 250)], False),
        ("over_per_partition_bar_with_small_files_compacts", [(1, [_MB] * 250)], True),
        ("md5_buckets_fragmented_compacts", [(16, [_MB] * 300)], True),
        # md5 buckets over the total bar, but each bucket already compacted to large files.
        ("md5_buckets_compacted_skips", [(150, [60 * _MB] * 40)], False),
        # Below the removable thresholds in every partition and in total, though over the total bar.
        ("few_removable_files_skips", [(5_100, [300_000]), (50, [300_000, 300_000])], False),
    ]

    @parameterized.expand(_COUNT_TRIGGER_CASES)
    @pytest.mark.asyncio
    async def test_count_trigger_needs_removable_files(
        self, _name: str, layout: list[tuple[int, list[int]]], expected_ran: bool
    ):
        mock_delta = _mock_table(_layout(layout))
        maintenance = _make_maintenance(mock_delta)
        with (
            patch.object(maintenance, "_compact", AsyncMock(return_value=True)) as mock_compact,
            patch.object(maintenance, "_plan_compaction", AsyncMock(return_value=_DEFAULT_PLAN)) as plan,
        ):
            ran = await maintenance.compact_if_fragmented()

        assert ran is expected_ran
        assert mock_compact.await_count == (1 if expected_ran else 0)
        # The decision reads the Delta log only. Planning reads parquet footers, so a skip must not plan.
        assert plan.await_count == (1 if expected_ran else 0)

    # (case_name, files_per_dir, dir_count, expected_ran)
    _DERIVATION_CASES: list[tuple[str, int, int, bool]] = [
        # 300 files / 3 partitions = 100 fpp < 200 and total < 5,000 -> skip. Read as one
        # partition (300 fpp), this healthy table compacts on every run.
        ("healthy_partitioned_table_skips", 100, 3, False),
        ("fragmented_partitioned_table_fires", 250, 3, True),
    ]

    @parameterized.expand(_DERIVATION_CASES)
    @pytest.mark.asyncio
    async def test_partition_count_derived_from_layout(
        self, _name: str, files_per_dir: int, dir_count: int, expected_ran: bool
    ):
        mock_delta = _mock_table(_layout([(dir_count, [_MB] * files_per_dir)]))
        maintenance = _make_maintenance(mock_delta)
        with (
            patch.object(maintenance, "_plan_compaction", AsyncMock(return_value=_DEFAULT_PLAN)),
            patch.object(maintenance, "_compact", AsyncMock(return_value=True)) as mock_compact,
        ):
            ran = await maintenance.compact_if_fragmented()

        assert ran is expected_ran
        assert mock_compact.await_count == (1 if expected_ran else 0)

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
        ("every_partition_grows_table_wide_check_fires", [(150, [20 * _MB, _MB])], True, True, True),
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
        mock_delta = _mock_table(_layout(layout))
        maintenance = _make_maintenance(mock_delta)
        with (
            override_settings(DATA_WAREHOUSE_TARGET_PARTITION_BYTES=500 * _MB),
            patch.object(maintenance, "_plan_compaction", AsyncMock(return_value=_DEFAULT_PLAN)),
            patch.object(maintenance, "_compact", AsyncMock(return_value=True)) as mock_compact,
        ):
            ran = await maintenance.compact_if_fragmented(
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

            ran = await _make_maintenance(table).compact_if_fragmented(compact_small_files=True)

            assert ran is expected_ran
            files_after = len(table.file_uris())
            assert (files_after < files_before) is expected_ran
            assert table.to_pyarrow_table().num_rows == rows_before

    @parameterized.expand(
        [
            # One file in each partition, as an hourly incremental table holds them: a no-op that adds no commit.
            ("one_file_per_partition", 30, 1, False, 0),
            # Thirty small files in one partition: one compaction commit, and no vacuum commits after it.
            ("fragmented_partition", 1, 30, True, 1),
        ]
    )
    @pytest.mark.asyncio
    async def test_count_trigger_on_a_real_table(
        self, _name: str, partitions: int, files_per_partition: int, expected_ran: bool, expected_commits: int
    ):
        with tempfile.TemporaryDirectory() as path:
            for part in range(partitions):
                for i in range(files_per_partition):
                    deltalake.write_deltalake(
                        path,
                        pa.table({"p": [f"h{part:03d}"], "id": [part * 1000 + i]}),
                        mode="append",
                        partition_by=["p"],
                    )
            table = deltalake.DeltaTable(path)
            version_before = table.version()
            rows_before = table.to_pyarrow_table().num_rows

            ran = await _make_maintenance(table).compact_if_fragmented(total_threshold=10)

            assert ran is expected_ran
            table.update_incremental()
            assert table.version() - version_before == expected_commits
            assert table.to_pyarrow_table().num_rows == rows_before


class TestCompactConflictRetry:
    @pytest.mark.asyncio
    async def test_retries_compact_on_commit_conflict_then_succeeds(self):
        # optimize.compact() commits a REMOVE+ADD when rewriting fragmented files — the same
        # commit-conflict shape as a merge (see test_ops.TestExecuteWithConflictRetry). Regression
        # coverage for a CommitFailedError propagating straight out on the first conflict instead of
        # retrying with a refreshed table, like the write merges do.
        mock_delta = _mock_table({f"{i}.parquet": _MB for i in range(12)})
        mock_delta.optimize.compact = MagicMock(
            side_effect=[
                deltalake.exceptions.CommitFailedError(
                    "Commit failed: a concurrent transaction deleted data this operation read."
                ),
                {"numFilesAdded": 1},
            ]
        )

        maintenance = _make_maintenance(mock_delta)
        with patch.object(maintenance, "_plan_compaction", AsyncMock(return_value=_DEFAULT_PLAN)):
            compacted = await maintenance.compact_if_fragmented(threshold=1)

        assert compacted is True
        assert mock_delta.optimize.compact.call_count == 2
        mock_delta.update_incremental.assert_called_once()
        mock_delta.vacuum.assert_not_called()


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

        await _make_maintenance(mock_delta)._compact(mock_delta, plan_compaction(1.0, None))

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
            await _make_maintenance(mock_delta)._compact(mock_delta, plan_compaction(1.0, None))

        assert mock_delta.optimize.compact.call_count == COMPACT_OFFSET_OVERFLOW_RETRIES + 1

    @pytest.mark.asyncio
    async def test_unrelated_delta_error_is_not_retried(self):
        mock_delta = MagicMock()
        mock_delta.optimize.compact = MagicMock(side_effect=deltalake.exceptions.DeltaError("no protocol found"))

        with pytest.raises(deltalake.exceptions.DeltaError):
            await _make_maintenance(mock_delta)._compact(mock_delta, plan_compaction(1.0, None))

        mock_delta.optimize.compact.assert_called_once()


class TestCompactionMemoryBounds:
    @parameterized.expand(
        [
            # Incompressible data keeps delta-rs's own bin size; the slot fits a few bins at once.
            ("incompressible", 1.0, 1356.8, DEFAULT_COMPACT_TARGET_SIZE_BYTES, 6),
            ("modest_ratio", 2.0, 1356.8, DEFAULT_COMPACT_TARGET_SIZE_BYTES, 3),
            # Wide JSON documents: 100 MB on disk decodes past the 2 GiB offset limit, so the bin shrinks
            # until it decodes to half the slot and only one bin runs at a time. delta-rs leaves files
            # larger than the bin alone, so the bin also caps the largest file that a compaction decodes.
            ("wide_json", 25.0, 1356.8, int(1356.8 * _MB / 2 / 25), 1),
            ("extreme_ratio_skips", 500.0, 1356.8, None, None),
            ("zero_budget_skips", 1.0, 0.0, None, None),
            # No readable limit (local dev): only the decoded bin is capped, delta-rs picks parallelism.
            ("no_limit", 25.0, None, int(1024 * _MB / 25), None),
            ("no_limit_no_ratio_skips", None, None, None, None),
        ]
    )
    def test_plan_keeps_one_compaction_inside_its_slot(
        self,
        _name: str,
        ratio: float | None,
        slot_mb: float | None,
        expected_target: int | None,
        expected_tasks: int | None,
    ) -> None:
        with patch(f"{_MAINTENANCE_MODULE}.os.cpu_count", return_value=7):
            plan = plan_compaction(ratio, slot_mb)

        assert plan.target_size == expected_target
        assert plan.max_concurrent_tasks == expected_tasks
        if slot_mb is not None and plan.max_concurrent_tasks is not None:
            assert plan.target_size is not None
            decoded_per_task = plan.target_size * max(ratio or 1.0, 1.0) * 2
            assert decoded_per_task * plan.max_concurrent_tasks <= slot_mb * _MB

    @pytest.mark.asyncio
    async def test_small_file_trigger_rechecks_removals_at_planned_target(self) -> None:
        file_sizes = {f"f{i}.parquet": 30 * _MB for i in range(30)}
        mock_delta = _mock_table(file_sizes)
        maintenance = _make_maintenance(mock_delta)
        plan = CompactionPlan(
            target_size=27 * _MB,
            max_concurrent_tasks=1,
            compression_ratio=25.0,
            slot_budget_mb=1356.8,
        )
        with (
            patch.object(maintenance, "_plan_compaction", AsyncMock(return_value=plan)),
            patch.object(maintenance, "_compact", AsyncMock()) as compact,
        ):
            ran = await maintenance.compact_if_fragmented(compact_small_files=True)

        assert ran is False
        compact.assert_not_awaited()

    @parameterized.expand(
        [
            ("compressible_json", True, 1),
            ("random", False, 1),
            # Several row groups per file: the footer sums every row group.
            ("many_row_groups", True, 4),
        ]
    )
    def test_samples_the_compression_ratio_from_footers_only(
        self, _name: str, compressible: bool, row_groups: int
    ) -> None:
        with tempfile.TemporaryDirectory() as path:
            for file_index in range(5):
                rows = 4 + file_index
                payloads = [
                    (json.dumps({"row": row}) + '{"field": "value", "n": 1}' * 4000)
                    if compressible
                    else os.urandom(50_000).hex()
                    for row in range(rows)
                ]
                deltalake.write_deltalake(
                    path,
                    pa.table({"id": list(range(rows)), "data": payloads}),
                    mode="append",
                    writer_properties=deltalake.WriterProperties(
                        compression="SNAPPY", max_row_group_size=max(1, rows // row_groups)
                    ),
                )
            table = deltalake.DeltaTable(path)

            with (
                patch.object(deltalake.DeltaTable, "to_pyarrow_dataset", side_effect=AssertionError("full dataset")),
                patch(f"{_MAINTENANCE_MODULE}.pq.read_metadata", wraps=pq.read_metadata) as read_metadata,
            ):
                ratio = _sample_compression_ratio(table)

            # The same footers through the dataset, the way the sampling worked before.
            by_size = sorted(table._table.get_add_file_sizes().items(), key=lambda item: -item[1])
            largest = {path.rpartition("/")[2] for path, _ in by_size[:_COMPACT_RATIO_SAMPLE_FILES]}
            decoded = stored = 0
            for fragment in table.to_pyarrow_dataset().get_fragments():
                if fragment.path.rpartition("/")[2] in largest:
                    metadata = fragment.metadata
                    for index in range(metadata.num_row_groups):
                        row_group = metadata.row_group(index)
                        decoded += row_group.total_byte_size
                        stored += sum(row_group.column(c).total_compressed_size for c in range(row_group.num_columns))

        assert read_metadata.call_count == _COMPACT_RATIO_SAMPLE_FILES
        assert ratio is not None
        assert ratio == pytest.approx(decoded / stored, rel=1e-9)
        if compressible:
            assert ratio > 10
        else:
            assert ratio < 3

    def test_samples_nothing_from_an_empty_table(self) -> None:
        table = MagicMock()
        table._table.get_add_file_sizes.return_value = {}
        assert _sample_compression_ratio(table) is None

    @pytest.mark.asyncio
    async def test_compact_runs_with_the_planned_bin_size_and_parallelism(self) -> None:
        mock_delta = MagicMock()
        mock_delta.optimize.compact = MagicMock(return_value={"numFilesAdded": 1, "numFilesRemoved": 4})
        with (
            patch(f"{_MAINTENANCE_MODULE}._sample_compression_ratio", return_value=25.0),
            patch(f"{_MAINTENANCE_MODULE}.get_governor") as governor,
        ):
            governor.return_value.slot_budget_mb.return_value = 1356.8
            governor.return_value.pod.current_mb.return_value = 4096.0
            await _make_maintenance(mock_delta)._compact(mock_delta)

        kwargs = mock_delta.optimize.compact.call_args.kwargs
        assert kwargs == {"target_size": int(1356.8 * _MB / 2 / 25), "max_concurrent_tasks": 1}

    @pytest.mark.asyncio
    async def test_offset_overflow_retry_runs_one_bin_at_a_time(self) -> None:
        mock_delta = MagicMock()
        mock_delta.optimize.compact = MagicMock(
            side_effect=[
                deltalake.exceptions.DeltaError(
                    'Generic error: task 7 panicked with message "byte array offset overflow"'
                ),
                {"numFilesAdded": 1},
            ]
        )
        with (
            patch(f"{_MAINTENANCE_MODULE}._sample_compression_ratio", return_value=1.0),
            patch(f"{_MAINTENANCE_MODULE}.get_governor") as governor,
            patch(f"{_MAINTENANCE_MODULE}.os.cpu_count", return_value=7),
        ):
            governor.return_value.slot_budget_mb.return_value = 1356.8
            governor.return_value.pod.current_mb.return_value = 4096.0
            await _make_maintenance(mock_delta)._compact(mock_delta)

        first, second = (call.kwargs for call in mock_delta.optimize.compact.call_args_list)
        assert first["max_concurrent_tasks"] == 6
        assert second == {"target_size": first["target_size"] // 2, "max_concurrent_tasks": 1}


class TestDeltaliteCompaction:
    _URI = "s3://bucket/table"
    _SLOT_MB = 1356.8

    def _setup(self, compact: MagicMock | None, *, table_id: object = "table-id") -> tuple[DeltaMaintenance, Any, Any]:
        # 300 small files in one partition trip the per-partition count trigger.
        delta_table = _mock_table({f"f{i}.parquet": _MB for i in range(300)})
        delta_table.metadata.return_value.id = table_id
        table_ref = MagicMock()
        table_ref.logger = make_logger()
        table_ref.get_delta_table = AsyncMock(return_value=delta_table)
        table_ref.get_table_uri = AsyncMock(return_value=self._URI)
        table_ref.get_storage_options = MagicMock(return_value={"AWS_REGION": "us-east-1"})
        table_ref.latest_known_version = MagicMock(return_value=150)
        table_ref.note_deltalite_commit = MagicMock()
        table_ref.job.id = "job-1"

        handle = MagicMock()
        handle.version.return_value = 151
        attributes: dict[str, Any] = {"open": staticmethod(MagicMock(return_value=handle))}
        if compact is not None:
            handle.compact = compact
            attributes["compact"] = compact
        fake_class = type("FakeDeltaLiteTable", (), attributes)
        return DeltaMaintenance(table_ref, clock=lambda: _NOW), table_ref, fake_class

    async def _run(
        self, maintenance: DeltaMaintenance, fake_class: Any, *, enabled: bool = True
    ) -> tuple[bool, AsyncMock, AsyncMock, MagicMock]:
        cache = DeltaLiteHandleCache(maxsize=2, opener=fake_class.open)
        with (
            override_settings(DATA_WAREHOUSE_DELTALITE_COMPACTION=enabled),
            patch.object(deltalite, "DeltaLiteTable", fake_class),
            patch(f"{_MAINTENANCE_MODULE}.get_handle_cache", return_value=cache),
            patch(f"{_MAINTENANCE_MODULE}.get_governor") as governor,
            patch(f"{_MAINTENANCE_MODULE}.os.cpu_count", return_value=7),
            patch(f"{_MAINTENANCE_MODULE}.capture_exception") as capture,
            patch.object(maintenance, "_plan_compaction", AsyncMock(return_value=_DEFAULT_PLAN)) as plan,
            patch.object(maintenance, "_compact", AsyncMock(return_value=True)) as delta_rs_compact,
        ):
            governor.return_value.slot_budget_mb.return_value = self._SLOT_MB
            governor.return_value.pod.current_mb.return_value = 4096.0
            ran = await maintenance.compact_if_fragmented()
        return ran, delta_rs_compact, plan, capture

    @staticmethod
    def _info_calls(table_ref: Any, message: str) -> list[dict[str, Any]]:
        return [call.kwargs for call in table_ref.logger.ainfo.call_args_list if call.args[:1] == (message,)]

    @parameterized.expand(
        [
            ("committed", 1, 152, [152]),
            ("nothing_to_rewrite", 0, 150, []),
        ]
    )
    @pytest.mark.asyncio
    async def test_compacts_through_a_leased_deltalite_handle(
        self, _name: str, commits: int, version: int, expected_noted: list[int]
    ) -> None:
        compact = MagicMock(
            return_value={"commits": commits, "version": version, "numFilesAdded": 3, "numFilesRemoved": 300}
        )
        maintenance, table_ref, fake_class = self._setup(compact)

        with patch(f"{_MAINTENANCE_MODULE}._sample_compression_ratio", side_effect=AssertionError("sampled")):
            ran, delta_rs_compact, plan, capture = await self._run(maintenance, fake_class)

        assert ran is True
        delta_rs_compact.assert_not_awaited()
        plan.assert_not_awaited()
        capture.assert_not_called()
        fake_class.open.assert_called_once_with(self._URI, {"AWS_REGION": "us-east-1"})
        compact.assert_called_once_with(
            target_file_size=DEFAULT_COMPACT_TARGET_SIZE_BYTES,
            max_parallel_bins=7,
            slot_budget_bytes=int(self._SLOT_MB * _MB),
            commit_metadata={"compact_engine": "deltalite", "job_id": "job-1"},
            min_partition_removable_files=1,
        )
        assert [call.args[0] for call in table_ref.note_deltalite_commit.call_args_list] == expected_noted
        [done] = self._info_calls(table_ref, "compact: done")
        assert done["compact_engine"] == "deltalite"
        assert (done["compact_files_added"], done["compact_files_removed"]) == (3, 300)

    @pytest.mark.asyncio
    async def test_opens_a_fresh_handle_when_the_table_identity_is_unknown(self) -> None:
        compact = MagicMock(return_value={"commits": 1, "version": 151})
        maintenance, _, fake_class = self._setup(compact, table_id=None)

        with patch.object(DeltaLiteHandleCache, "lease") as lease:
            ran, _, _, _ = await self._run(maintenance, fake_class)

        assert ran is True
        lease.assert_not_called()
        compact.assert_called_once()

    @parameterized.expand(
        [
            ("setting_off", False, True, None, None, False),
            ("wheel_without_compact", True, False, None, "deltalite_compact_unavailable", False),
            (
                "unsupported_table",
                True,
                True,
                deltalite.DeltaLiteUnsupportedTableError("deletion vectors are not supported"),
                "unsupported_table",
                False,
            ),
            (
                "unexpected_deltalite_error",
                True,
                True,
                deltalite.DeltaLiteError("parquet decode failed"),
                "deltalite_error",
                True,
            ),
        ]
    )
    @pytest.mark.asyncio
    async def test_falls_back_to_delta_rs(
        self,
        _name: str,
        enabled: bool,
        has_compact: bool,
        error: Exception | None,
        expected_reason: str | None,
        expect_capture: bool,
    ) -> None:
        compact = MagicMock(side_effect=error) if has_compact else None
        maintenance, table_ref, fake_class = self._setup(compact)

        ran, delta_rs_compact, _, capture = await self._run(maintenance, fake_class, enabled=enabled)

        assert ran is True
        delta_rs_compact.assert_awaited_once_with(table_ref.get_delta_table.return_value, _DEFAULT_PLAN)
        fallbacks = self._info_calls(table_ref, "compact: falling back to delta-rs")
        assert [call["compact_fallback_reason"] for call in fallbacks] == ([expected_reason] if expected_reason else [])
        assert capture.called is expect_capture
        if not enabled and compact is not None:
            compact.assert_not_called()

    @pytest.mark.asyncio
    async def test_commit_conflict_skips_the_pass_without_reporting(self) -> None:
        compact = MagicMock(side_effect=deltalite.DeltaLiteCommitConflictError("schema changed"))
        maintenance, table_ref, fake_class = self._setup(compact)

        ran, delta_rs_compact, _, capture = await self._run(maintenance, fake_class)

        assert ran is False
        delta_rs_compact.assert_not_awaited()
        capture.assert_not_called()
        table_ref.note_deltalite_commit.assert_not_called()

    @parameterized.expand(
        [
            (
                "permission_denied",
                "Generic S3 error: Access Denied for _delta_log/00001.json",
                ObjectStorePermissionDeniedError,
            ),
            ("transient", "Generic S3 error: Please reduce your request rate", TransientObjectStoreError),
        ]
    )
    @pytest.mark.asyncio
    async def test_object_store_errors_use_the_existing_classifiers(
        self, _name: str, message: str, expected: type[Exception]
    ) -> None:
        compact = MagicMock(side_effect=deltalite.DeltaLiteError(message))
        maintenance, table_ref, fake_class = self._setup(compact)

        with pytest.raises(expected) as raised:
            await self._run(maintenance, fake_class)

        assert "_delta_log" not in str(raised.value)
        assert "_delta_log" not in str(table_ref.logger.method_calls)
        assert isinstance(raised.value.__cause__, deltalite.DeltaLiteError)


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

    @parameterized.expand([("lite", False), ("full", True)])
    @pytest.mark.asyncio
    async def test_lite_and_full_share_the_retention(self, _name: str, full: bool):
        mock_delta = MagicMock()
        mock_delta.vacuum = MagicMock(return_value=["a.parquet", "b.parquet"])

        deleted = await _make_maintenance(mock_delta)._vacuum(mock_delta, full=full)

        assert deleted == 2
        mock_delta.vacuum.assert_called_once_with(
            retention_hours=24, enforce_retention_duration=False, dry_run=False, full=full
        )


def _watermarks(version: int | None, vacuumed_days_ago: float | None, full_days_ago: float | None) -> VacuumWatermarks:
    def at(days: float | None) -> dt.datetime | None:
        return None if days is None else _NOW - dt.timedelta(days=days)

    return VacuumWatermarks(version=version, vacuumed_at=at(vacuumed_days_ago), full_vacuumed_at=at(full_days_ago))


class TestDecideVacuum:
    @parameterized.expand(
        [
            # (name, version watermark, days since vacuum, days since full vacuum, expected reason,
            # expected seeded version) at version 150, a 100-commit cadence, 5-day and 7-day intervals.
            # A first encounter seeds every watermark without vacuuming, so existing tables do not all
            # vacuum at once on deploy.
            ("first_encounter_seeds", None, None, None, None, 150),
            ("existing_table_seeds_timestamps", 100, None, None, None, 100),
            ("below_every_cadence_skips", 100, 1, 1, None, 100),
            ("commit_cadence_due", 50, 1, 1, "commits", 50),
            ("above_commit_cadence_due", 40, 1, 1, "commits", 40),
            # A table that commits slowly vacuums on time, before a checkpoint drops its tombstones.
            ("time_cadence_due", 149, 5, 1, "time", 149),
            ("time_cadence_just_under_skips", 149, 5 - 1 / 86400, 1, None, 149),
            ("full_vacuum_weekly", 149, 1, 7, "full", 149),
            # A full vacuum deletes everything a lite one does, so it replaces a due lite vacuum.
            ("full_replaces_commit_vacuum", 10, 6, 8, "full", 10),
            # A watermark above the current version means the table was recreated. It must reseed, not
            # block the commit cadence until the new table catches up.
            ("recreated_table_reseeds", 999, 1, 1, None, 150),
            ("recreated_table_still_vacuums_on_time", 999, 6, 1, "time", 150),
            # A watermark in the future (clock skew) is never due.
            ("future_watermarks_skip", 149, -1, -1, None, 149),
        ]
    )
    def test_cadence(
        self,
        _name: str,
        version: int | None,
        vacuumed_days_ago: float | None,
        full_days_ago: float | None,
        expected_reason: str | None,
        expected_version: int,
    ):
        watermarks = _watermarks(version, vacuumed_days_ago, full_days_ago)

        decision = decide_vacuum(watermarks, _CADENCE, 150, _NOW)

        assert decision.reason == expected_reason
        assert decision.full is (expected_reason == "full")
        assert decision.watermarks.version == expected_version
        assert decision.watermarks.vacuumed_at == (watermarks.vacuumed_at or _NOW)
        assert decision.watermarks.full_vacuumed_at == (watermarks.full_vacuumed_at or _NOW)

    def test_time_cadence_vacuums_before_a_checkpoint_can_drop_a_tombstone(self):
        cadence = VacuumCadence.from_settings()
        # A tombstone ages past the retention, then a vacuum is due at most `max_interval` later.
        assert cadence.max_interval + VACUUM_RETENTION < DELTA_DELETED_FILE_RETENTION
        assert cadence.commit_threshold == settings.DATA_WAREHOUSE_VACUUM_COMMIT_THRESHOLD
        assert cadence.full_interval >= cadence.max_interval


class TestVacuumWatermarks:
    @parameterized.expand(
        [
            ("snapshot", False, "last_vacuum_version", "last_vacuum_at", "last_full_vacuum_at"),
            # The _cdc companion is another delta table with unrelated versions, so it keeps its own keys.
            ("companion", True, "last_vacuum_version_cdc", "last_vacuum_at_cdc", "last_full_vacuum_at_cdc"),
        ]
    )
    def test_round_trips_through_sync_type_config(
        self, _name: str, is_cdc_companion: bool, version_key: str, vacuumed_key: str, full_key: str
    ):
        watermarks = _watermarks(42, 1, 3)
        config = watermarks.config_updates(
            VacuumWatermarks(version=None, vacuumed_at=None, full_vacuumed_at=None), is_cdc_companion
        )

        assert set(config) == {version_key, vacuumed_key, full_key}
        assert VacuumWatermarks.from_config(config, is_cdc_companion) == watermarks
        assert VacuumWatermarks.from_config(config, not is_cdc_companion) == VacuumWatermarks(
            version=None, vacuumed_at=None, full_vacuumed_at=None
        )

    @parameterized.expand([("not_a_string", 12), ("not_a_timestamp", "yesterday")])
    def test_unreadable_timestamp_reads_as_missing(self, _name: str, value: object):
        watermarks = VacuumWatermarks.from_config({"last_vacuum_at": value}, False)
        assert watermarks.vacuumed_at is None

    def test_unchanged_values_are_not_rewritten(self):
        watermarks = _watermarks(42, 1, 3)
        assert watermarks.config_updates(watermarks, False) == {}


class TestVacuumIfDue:
    @parameterized.expand(
        [
            # (name, watermarks, expected reason)
            ("not_due", _watermarks(100, 1, 1), None),
            ("commits", _watermarks(40, 1, 1), "commits"),
            ("time", _watermarks(149, 6, 1), "time"),
            ("full", _watermarks(149, 1, 8), "full"),
        ]
    )
    @pytest.mark.asyncio
    async def test_vacuums_when_due(self, _name: str, watermarks: VacuumWatermarks, expected_reason: str | None):
        table = MagicMock()
        # Vacuum commits its own start and end entries.
        table.version = MagicMock(side_effect=[150, 152])
        maintenance = _make_maintenance(table)
        with (
            patch.object(maintenance, "_vacuum", new=AsyncMock(return_value=3)) as vacuum,
            patch(f"{_MAINTENANCE_MODULE}.posthoganalytics") as ph,
        ):
            decision = await maintenance.vacuum_if_due(watermarks, _CADENCE)

        assert decision is not None
        assert decision.reason == expected_reason
        if expected_reason is None:
            vacuum.assert_not_awaited()
            ph.capture.assert_not_called()
            assert decision.watermarks == watermarks
            return
        vacuum.assert_awaited_once_with(table, full=expected_reason == "full")
        assert decision.watermarks.version == 152
        assert decision.watermarks.vacuumed_at == _NOW
        assert decision.watermarks.full_vacuumed_at == (
            _NOW if expected_reason == "full" else watermarks.full_vacuumed_at
        )
        properties = ph.capture.call_args.kwargs["properties"]
        assert ph.capture.call_args.kwargs["event"] == "warehouse_delta_vacuumed"
        assert properties["vacuum_reason"] == expected_reason
        assert properties["files_deleted"] == 3

    @pytest.mark.asyncio
    async def test_no_table(self):
        assert await _make_maintenance(None).vacuum_if_due(_watermarks(1, 1, 1), _CADENCE) is None


class TestRunScheduled:
    """run_scheduled owns the vacuum-watermark lifecycle for both call sites (pre-write defensive
    pass and post-load), so watermark-key selection, persistence gating, and the never-raise
    contract all live here."""

    def _schema(self, config: dict | None = None) -> MagicMock:
        schema = MagicMock()
        schema.partition_count = 10
        schema.sync_type_config = (
            config
            if config is not None
            else {
                "last_vacuum_version": 41,
                "last_vacuum_at": (_NOW - dt.timedelta(days=1)).isoformat(),
                "last_full_vacuum_at": (_NOW - dt.timedelta(days=1)).isoformat(),
                "last_vacuum_version_cdc": 7,
                "last_vacuum_at_cdc": (_NOW - dt.timedelta(days=1)).isoformat(),
                "last_full_vacuum_at_cdc": (_NOW - dt.timedelta(days=1)).isoformat(),
            }
        )
        return schema

    async def _run(
        self,
        maintenance: DeltaMaintenance,
        schema: MagicMock,
        *,
        is_cdc_companion: bool = False,
        compact_small_files: bool = False,
        compact: AsyncMock | None = None,
        vacuum: AsyncMock | None = None,
    ) -> tuple[AsyncMock, AsyncMock, MagicMock, MagicMock]:
        compact = compact or AsyncMock(return_value=False)
        vacuum = vacuum or AsyncMock(return_value=0)
        with (
            patch.object(maintenance, "compact_if_fragmented", compact),
            patch.object(maintenance, "_vacuum", vacuum),
            patch(f"{_MAINTENANCE_MODULE}.posthoganalytics"),
            patch(f"{_MAINTENANCE_MODULE}.database_sync_to_async_pool", _passthrough_pool),
            patch(f"{_MAINTENANCE_MODULE}.update_sync_type_config_keys") as update_config,
            patch(f"{_MAINTENANCE_MODULE}.capture_exception") as capture,
        ):
            await maintenance.run_scheduled(
                schema,
                is_cdc_companion=is_cdc_companion,
                compact_small_files=compact_small_files,
            )
        return compact, vacuum, update_config, capture

    @parameterized.expand(
        [
            ("main", False, "last_vacuum_version"),
            # The snapshot and _cdc companion are different delta tables with unrelated versions, so
            # the companion must use its own keys. Sharing a key corrupts both cadences.
            ("companion_own_key", True, "last_vacuum_version_cdc"),
        ]
    )
    @pytest.mark.asyncio
    async def test_watermark_key_selection(self, _name: str, is_cdc_companion: bool, expected_key: str):
        schema = self._schema()
        # 150 - 41 and 150 - 7 are both past the 100-commit cadence.
        table = MagicMock(version=MagicMock(side_effect=[150, 152]))
        compact, vacuum, update_config, _ = await self._run(
            _make_maintenance(table), schema, is_cdc_companion=is_cdc_companion
        )

        compact.assert_awaited_once()
        vacuum.assert_awaited_once()
        suffix = "_cdc" if is_cdc_companion else ""
        expected_updates = {expected_key: 152, f"last_vacuum_at{suffix}": _NOW.isoformat()}
        update_config.assert_called_once_with(schema.id, schema.team_id, updates=expected_updates)
        assert schema.sync_type_config[expected_key] == 152

    # (name, schema.partition_count, is_cdc_companion, layout or None for 250 unpartitioned files,
    # expected_ran). Two small files in each of 1,000 partitions: 2 files per partition, and 2,000
    # files in total, under both count bars.
    _STORED_PARTITION_COUNT_CASES: list[tuple[str, int | None, bool, list[tuple[int, list[int]]] | None, bool]] = [
        # Every partition mode stores the source's count, so a datetime table can store 1. Read as
        # one partition, the table compacts every one of its partitions on every sync.
        ("stored_count_below_partition_directories_skips", 1, False, [(1_000, [300_000, 300_000])], False),
        ("md5_count_matching_directories_fragmented_compacts", 16, False, [(16, [_MB] * 300)], True),
        ("md5_count_matching_directories_healthy_skips", 16, False, [(16, [_MB] * 100)], False),
        # A table that existed unpartitioned keeps its layout, whatever count the schema stores.
        ("unpartitioned_table_ignores_stored_count", 10, False, None, True),
        ("unpartitioned_table_without_stored_count", None, False, None, True),
        # The schema's count describes the snapshot table, not the companion.
        ("cdc_companion_ignores_snapshot_count", 1_000, True, None, True),
        ("cdc_companion_ignores_low_snapshot_count", 1, True, [(1_000, [300_000, 300_000])], False),
    ]

    @parameterized.expand(_STORED_PARTITION_COUNT_CASES)
    @pytest.mark.asyncio
    async def test_compaction_counts_partitions_from_the_layout(
        self,
        _name: str,
        stored_partition_count: int | None,
        is_cdc_companion: bool,
        layout: list[tuple[int, list[int]]] | None,
        expected_ran: bool,
    ):
        schema = self._schema()
        schema.partition_count = stored_partition_count
        file_sizes = _layout(layout) if layout is not None else {f"f{i}.parquet": _MB for i in range(250)}
        maintenance = _make_maintenance(_mock_table(file_sizes))
        with (
            patch.object(maintenance, "_plan_compaction", AsyncMock(return_value=_DEFAULT_PLAN)),
            patch.object(maintenance, "_compact", AsyncMock(return_value=True)) as mock_compact,
        ):
            await self._run(
                maintenance,
                schema,
                is_cdc_companion=is_cdc_companion,
                compact=AsyncMock(side_effect=maintenance.compact_if_fragmented),
            )

        assert mock_compact.await_count == (1 if expected_ran else 0)

    @parameterized.expand(
        [
            ("first_encounter_seeds_without_vacuum", {}, True, False),
            (
                "nothing_due_writes_nothing",
                {
                    "last_vacuum_version": 100,
                    "last_vacuum_at": (_NOW - dt.timedelta(days=1)).isoformat(),
                    "last_full_vacuum_at": (_NOW - dt.timedelta(days=1)).isoformat(),
                },
                False,
                False,
            ),
            (
                "due_vacuum_persists",
                {
                    "last_vacuum_version": 10,
                    "last_vacuum_at": (_NOW - dt.timedelta(days=1)).isoformat(),
                    "last_full_vacuum_at": (_NOW - dt.timedelta(days=1)).isoformat(),
                },
                True,
                True,
            ),
        ]
    )
    @pytest.mark.asyncio
    async def test_watermark_persistence_gating(
        self, _name: str, config: dict, expect_write: bool, expect_vacuum: bool
    ):
        schema = self._schema(config)
        table = MagicMock(version=MagicMock(return_value=150))
        _, vacuum, update_config, _ = await self._run(_make_maintenance(table), schema)

        assert update_config.called is expect_write
        assert vacuum.await_count == (1 if expect_vacuum else 0)

    @pytest.mark.asyncio
    async def test_compaction_does_not_vacuum_unless_due(self):
        table = MagicMock(version=MagicMock(return_value=50))
        compact = AsyncMock(return_value=True)
        _, vacuum, update_config, _ = await self._run(_make_maintenance(table), self._schema(), compact=compact)

        compact.assert_awaited_once()
        vacuum.assert_not_awaited()
        update_config.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_failing_compaction_keeps_the_vacuum_cadence(self):
        # A compaction that fails on every sync must not stop the vacuum, or its table leaks dead files.
        schema = self._schema()
        table = MagicMock(version=MagicMock(side_effect=[150, 152]))
        compact = AsyncMock(side_effect=RuntimeError("compaction blew up"))
        _, vacuum, update_config, capture = await self._run(_make_maintenance(table), schema, compact=compact)

        vacuum.assert_awaited_once()
        update_config.assert_called_once()
        capture.assert_called_once()

    @pytest.mark.asyncio
    async def test_pre_write_and_post_load_passes_vacuum_once(self):
        # Both passes of one sync share the schema object. The post-load pass must see the vacuum that
        # the pre-write pass persisted, and still run the table-wide small-file check that it skipped.
        schema = self._schema({"last_vacuum_version": 10})
        schema.sync_type_config.update(
            last_vacuum_at=(_NOW - dt.timedelta(days=1)).isoformat(),
            last_full_vacuum_at=(_NOW - dt.timedelta(days=1)).isoformat(),
        )
        table = MagicMock(version=MagicMock(side_effect=[150, 152, 155]))
        maintenance = _make_maintenance(table)
        vacuum = AsyncMock(return_value=0)
        pre_compact, _, pre_update, _ = await self._run(maintenance, schema, vacuum=vacuum)
        post_compact, _, post_update, _ = await self._run(maintenance, schema, compact_small_files=True, vacuum=vacuum)

        vacuum.assert_awaited_once()
        pre_update.assert_called_once()
        post_update.assert_not_called()
        assert pre_compact.await_args is not None and post_compact.await_args is not None
        assert pre_compact.await_args.kwargs["table_wide_small_files"] is False
        assert post_compact.await_args.kwargs["table_wide_small_files"] is True

    @parameterized.expand(
        [
            # (name, compact_small_files, version watermark, days since vacuum, expected_table_wide) at
            # version 150 with a 100-commit cadence.
            ("vacuum_due", True, 40, 1, True),
            ("vacuum_not_due", True, 100, 1, False),
            ("vacuumed_earlier_in_this_job", True, 149, 0.01, True),
            ("watermark_not_seeded", True, None, None, False),
            ("small_file_triggers_off", False, 40, 1, False),
        ]
    )
    @pytest.mark.asyncio
    async def test_table_wide_small_file_trigger_follows_the_vacuum_cadence(
        self,
        _name: str,
        compact_small_files: bool,
        version: int | None,
        vacuumed_days_ago: float | None,
        expected_table_wide: bool,
    ):
        config: dict = {}
        if version is not None:
            config["last_vacuum_version"] = version
        if vacuumed_days_ago is not None:
            config["last_vacuum_at"] = (_NOW - dt.timedelta(days=vacuumed_days_ago)).isoformat()
            config["last_full_vacuum_at"] = (_NOW - dt.timedelta(days=1)).isoformat()
        table = MagicMock(version=MagicMock(side_effect=[150, 152]))
        compact, _, _, _ = await self._run(
            _make_maintenance(table), self._schema(config), compact_small_files=compact_small_files
        )

        assert compact.await_args is not None
        assert compact.await_args.kwargs["compact_small_files"] is compact_small_files
        assert compact.await_args.kwargs["table_wide_small_files"] is expected_table_wide

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
            # re-attempting the vacuum instead of waiting for a cleanup that never ran.
            ("object_store_refusal_warned_only", ObjectStorePermissionDeniedError("denied"), False),
        ]
    )
    @pytest.mark.asyncio
    async def test_never_raises(self, _name: str, error: Exception, expect_capture: bool):
        maintenance = _make_maintenance(MagicMock(version=MagicMock(return_value=150)))
        logger = make_logger()
        maintenance._logger = logger

        _, _, update_config, capture = await self._run(
            maintenance, self._schema({"last_vacuum_version": 10}), vacuum=AsyncMock(side_effect=error)
        )

        assert capture.called is expect_capture
        update_config.assert_not_called()
        if expect_capture:
            logger.aexception.assert_awaited_once()
        else:
            logger.awarning.assert_awaited_once()


class TestVacuumOnARealTable:
    """Lite vacuum finds dead files only through tombstones, and a checkpoint drops tombstones older
    than `delta.deletedFileRetentionDuration`. These tests shorten that window to one second."""

    def _table_with_dropped_tombstones(self, root: str) -> None:
        config = {"delta.checkpointInterval": "5", "delta.deletedFileRetentionDuration": "interval 1 seconds"}
        deltalake.write_deltalake(
            root, pa.table({"p": ["a"] * 3, "x": [1, 2, 3]}), partition_by=["p"], configuration=config
        )
        for _ in range(3):
            deltalake.write_deltalake(
                root, pa.table({"p": ["a"] * 3, "x": [1, 2, 3]}), partition_by=["p"], mode="overwrite"
            )
        assert len(_dead_files(root)) == 3
        # The tombstones must age past the window before the next checkpoint drops them.
        time.sleep(1.1)
        for i in range(6):
            deltalake.write_deltalake(root, pa.table({"p": ["b"], "x": [i]}), partition_by=["p"], mode="append")

    @pytest.mark.asyncio
    async def test_periodic_full_vacuum_collects_files_lite_vacuum_misses(self):
        with tempfile.TemporaryDirectory() as root, patch(f"{_MAINTENANCE_MODULE}.VACUUM_RETENTION", dt.timedelta(0)):
            self._table_with_dropped_tombstones(root)
            table = deltalake.DeltaTable(root)
            rows = table.to_pyarrow_table().num_rows

            # The leak: the tombstones are gone from the checkpoint, so a lite vacuum deletes nothing.
            maintenance = _make_maintenance(table)
            await maintenance._vacuum(table)
            assert len(_dead_files(root)) == 3

            # The weekly full vacuum lists the table and deletes them.
            watermarks = VacuumWatermarks(
                version=table.version(), vacuumed_at=_NOW, full_vacuumed_at=_NOW - dt.timedelta(days=7)
            )
            with patch(f"{_MAINTENANCE_MODULE}.posthoganalytics"):
                decision = await maintenance.vacuum_if_due(watermarks, _CADENCE)

            assert decision is not None and decision.reason == "full"
            assert decision.watermarks.full_vacuumed_at == _NOW
            assert _dead_files(root) == set()
            assert deltalake.DeltaTable(root).to_pyarrow_table().num_rows == rows

    @pytest.mark.asyncio
    async def test_time_cadence_vacuums_a_slow_table_before_its_tombstones_drop(self):
        with tempfile.TemporaryDirectory() as root, patch(f"{_MAINTENANCE_MODULE}.VACUUM_RETENTION", dt.timedelta(0)):
            deltalake.write_deltalake(root, pa.table({"x": [1, 2, 3]}))
            for _ in range(3):
                deltalake.write_deltalake(root, pa.table({"x": [1, 2, 3]}), mode="overwrite")
            table = deltalake.DeltaTable(root)
            assert len(_dead_files(root)) == 3

            # Three commits since the last vacuum: the commit cadence is far from due, the time cadence is due.
            watermarks = VacuumWatermarks(
                version=table.version() - 3,
                vacuumed_at=_NOW - dt.timedelta(days=5),
                full_vacuumed_at=_NOW - dt.timedelta(days=1),
            )
            with patch(f"{_MAINTENANCE_MODULE}.posthoganalytics"):
                decision = await _make_maintenance(table).vacuum_if_due(watermarks, _CADENCE)

            assert decision is not None and decision.reason == "time"
            assert _dead_files(root) == set()

    @pytest.mark.asyncio
    async def test_full_vacuum_keeps_recent_tombstones_new_files_and_sibling_folders(self):
        # A full vacuum keeps the same 24-hour retention as a lite one: a reader pinned to a recent
        # version still needs a file that was tombstoned within it, however old the file is.
        with tempfile.TemporaryDirectory() as parent:
            root = os.path.join(parent, "table")
            deltalake.write_deltalake(root, pa.table({"x": [1, 2, 3]}))
            old = time.time() - 3 * 86400
            for name in _parquet_files(root):
                os.utime(os.path.join(root, name), (old, old))
            deltalake.write_deltalake(root, pa.table({"x": [4]}), mode="overwrite")
            recently_tombstoned = _dead_files(root)
            assert len(recently_tombstoned) == 1

            stale_orphan = os.path.join(root, "stale-orphan.parquet")
            new_orphan = os.path.join(root, "new-orphan.parquet")
            for path in (stale_orphan, new_orphan):
                pq.write_table(pa.table({"x": [0]}), path)
            os.utime(stale_orphan, (old, old))
            # The queryable folder copy sits next to the table, under a name that the table name prefixes.
            sibling = os.path.join(parent, "table__query", "copy.parquet")
            os.makedirs(os.path.dirname(sibling))
            pq.write_table(pa.table({"x": [0]}), sibling)
            os.utime(sibling, (old, old))

            table = deltalake.DeltaTable(root)
            deleted = await _make_maintenance(table)._vacuum(table, full=True)

            assert deleted == 1
            assert not os.path.exists(stale_orphan)
            assert os.path.exists(new_orphan)
            assert os.path.exists(sibling)
            assert recently_tombstoned <= _parquet_files(root)
            assert deltalake.DeltaTable(root).to_pyarrow_table().num_rows == 1
