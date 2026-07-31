import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import deltalake
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.maintenance import DeltaMaintenance

_MAINTENANCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.maintenance"


def _make_logger():
    return MagicMock(adebug=AsyncMock(), ainfo=AsyncMock(), awarning=AsyncMock(), aexception=AsyncMock())


def _make_maintenance(delta_table: MagicMock | None) -> DeltaMaintenance:
    table_ref = MagicMock()
    table_ref.logger = _make_logger()
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


class TestCompactTable:
    @pytest.mark.asyncio
    async def test_does_not_refetch_table_for_the_vacuum_step(self):
        # Regression: compact_table used to finish its own compact, then call vacuum_table(),
        # which called get_delta_table() again instead of reusing the table already in hand.
        # get_delta_table() is cached only opportunistically (a concurrent sync of a different
        # table can evict this table's cache entry), so that second call could come back None
        # and raise "Deltatable not found" right after a successful compact. Asserting a single
        # get_delta_table() call locks in that the vacuum step reuses the resolved table instead
        # of re-deriving it.
        mock_delta = MagicMock()
        mock_delta.optimize.compact = MagicMock(return_value={})
        mock_delta.vacuum = MagicMock(return_value=[])
        maintenance = _make_maintenance(mock_delta)

        await maintenance.compact_table()

        maintenance._table.get_delta_table.assert_called_once()
        mock_delta.optimize.compact.assert_called_once()
        mock_delta.vacuum.assert_called_once()

    @pytest.mark.asyncio
    async def test_retries_compact_on_commit_conflict_then_succeeds(self):
        # compact_table's optimize.compact() commits a REMOVE+ADD when rewriting fragmented files —
        # the same commit-conflict shape as a merge (see test_ops.TestExecuteWithConflictRetry).
        # Regression coverage for a CommitFailedError propagating straight out of compact_table on
        # the first conflict instead of retrying with a refreshed table, like the write merges do.
        mock_delta = MagicMock()
        mock_delta.optimize.compact = MagicMock(
            side_effect=[
                deltalake.exceptions.CommitFailedError(
                    "Commit failed: a concurrent transaction deleted data this operation read."
                ),
                {"numFilesAdded": 1},
            ]
        )
        mock_delta.vacuum = MagicMock(return_value=[])

        await _make_maintenance(mock_delta).compact_table()

        assert mock_delta.optimize.compact.call_count == 2
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


class TestRunScheduled:
    """run_scheduled owns the vacuum-watermark lifecycle for both call sites (pre-write defensive
    pass and CDC post-load), so watermark-key selection, persistence gating, and the never-raise
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
                schema, is_cdc_companion=is_cdc_companion, partition_count_fallback=partition_count_fallback
            )
        return run_maintenance, update_config, capture

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
        ]
    )
    @pytest.mark.asyncio
    async def test_never_raises(self, _name: str, error: Exception, expect_capture: bool):
        logger = _make_logger()
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
