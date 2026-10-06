import uuid
from datetime import UTC, datetime
from typing import Optional

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.db import OperationalError

import pyarrow as pa
from parameterized import parameterized

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.external_data_job import Any_Source_Errors
from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.load import (
    IncrementalFieldMissingFromDataError,
    get_incremental_field_value,
    notify_revenue_analytics_that_sync_has_completed,
    run_post_load_operations,
    update_job_row_count,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.maintenance import DeltaMaintenance
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.post_load_phases import (
    SUMMARY_EVENT,
    record_post_load_phases,
)
from products.warehouse_sources.backend.temporal.data_imports.query_folder_state import QueryFolderPointerHistory
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.constants import (
    CHARGE_RESOURCE_NAME as STRIPE_CHARGE_RESOURCE_NAME,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_LOAD_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.common.load"
_DB_RETRY_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.common.db_retry"
_PIPELINE_SYNC_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_sync"
_REPARTITION_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.repartition_controller"


def _make_schema(
    *,
    is_cdc: bool,
    sync_type_config: dict | None = None,
    partition_count: int | None = 7,
    cdc_table_mode: str = "consolidated",
    initial_sync_complete: bool = True,
) -> MagicMock:
    config = sync_type_config if sync_type_config is not None else {}
    schema = MagicMock()
    schema.id = uuid.uuid4()
    schema.team_id = 1
    schema.is_cdc = is_cdc
    schema.sync_type = ExternalDataSchema.SyncType.CDC if is_cdc else ExternalDataSchema.SyncType.INCREMENTAL
    schema.sync_type_config = config
    schema.last_vacuum_version = config.get("last_vacuum_version")
    schema.last_vacuum_version_cdc = config.get("last_vacuum_version_cdc")
    schema.partition_count = partition_count
    schema.cdc_table_mode = cdc_table_mode
    schema.initial_sync_complete = initial_sync_complete
    return schema


def _make_helper(*, file_uris: list[str] | None = None, live_row_count: int | None = None) -> MagicMock:
    return MagicMock(
        get_delta_table=AsyncMock(return_value=MagicMock()),
        get_file_uris=AsyncMock(return_value=file_uris or []),
        get_live_row_count=AsyncMock(return_value=live_row_count),
    )


async def _run_post_load(
    schema: MagicMock,
    helper: MagicMock,
    *,
    cdc_write_mode: str | None = None,
    resource: Optional[MagicMock] = None,
    stored_sync_type_config: dict | None = None,
    validate: AsyncMock | None = None,
    row_count: int = 10,
) -> tuple[AsyncMock, AsyncMock]:
    job = MagicMock()
    job.id = uuid.uuid4()
    job.team_id = schema.team_id
    logger = MagicMock(adebug=AsyncMock(), ainfo=AsyncMock())

    prepare_s3 = AsyncMock(return_value="orders__query_1")
    run_scheduled = AsyncMock()
    with (
        patch(f"{_LOAD_MODULE}.prepare_s3_files_for_querying", prepare_s3),
        patch(f"{_LOAD_MODULE}.own_linked_table", lambda schema, _pipeline: schema.table),
        patch(f"{_LOAD_MODULE}._stored_sync_type_config", MagicMock(return_value=stored_sync_type_config)),
        patch(f"{_LOAD_MODULE}.notify_revenue_analytics_that_sync_has_completed", AsyncMock()),
        patch(f"{_LOAD_MODULE}.sync_revenue_analytics_views", MagicMock()),
        patch(f"{_LOAD_MODULE}.DataWarehouseTable", MagicMock()),
        patch(f"{_LOAD_MODULE}.set_initial_sync_complete", AsyncMock()),
        patch.object(DeltaMaintenance, "run_scheduled", run_scheduled),
        patch(f"{_PIPELINE_SYNC_MODULE}.update_last_synced_at", AsyncMock()),
        patch(f"{_PIPELINE_SYNC_MODULE}.validate_schema_and_update_table", validate or AsyncMock()),
        patch(f"{_PIPELINE_SYNC_MODULE}.register_cdc_companion_table", AsyncMock()),
        patch(f"{_REPARTITION_MODULE}.maybe_flag_for_repartition", AsyncMock()),
    ):
        await run_post_load_operations(
            job=job,
            schema=schema,
            source=MagicMock(),
            delta_table_ref=helper,
            row_count=row_count,
            table_schema_dict={},
            resource_name="orders",
            logger=logger,
            resource=resource,
            cdc_write_mode=cdc_write_mode,
        )
    return run_scheduled, prepare_s3


class TestRunPostLoadDeltaMaintenance:
    """Post-load routes every schema kind through threshold maintenance; the threshold/watermark
    mechanics themselves are covered in core/delta/test/test_maintenance.py."""

    @parameterized.expand([("cdc", True, "incremental", False), ("non_cdc", False, None, True)])
    @pytest.mark.asyncio
    async def test_uses_threshold_maintenance_not_unconditional_compact(
        self, _name: str, is_cdc: bool, cdc_write_mode: str | None, compact_small_files: bool
    ) -> None:
        # CDC finals land every tick, and a non-CDC final batch usually leaves nothing to compact,
        # so an unconditional compact+vacuum here paid a full file listing and rewrite plan per sync.
        # A non-CDC table still needs its small merge files compacted: without that they pile up in
        # the newest partition, reads slow down, and the inflated partition trips a false repartition.
        schema = _make_schema(is_cdc=is_cdc, sync_type_config={"last_vacuum_version": 41})

        run_scheduled, _ = await _run_post_load(schema, _make_helper(), cdc_write_mode=cdc_write_mode)

        run_scheduled.assert_awaited_once_with(schema, is_cdc_companion=False, compact_small_files=compact_small_files)

    @pytest.mark.asyncio
    async def test_cdc_companion_write_runs_companion_maintenance(self):
        # The snapshot and _cdc companion are different delta tables, so a companion (scd2_append)
        # write must run maintenance in companion mode — run_scheduled then uses the companion's own
        # watermark key and layout instead of the snapshot's (see test_maintenance.TestRunScheduled).
        schema = _make_schema(is_cdc=True, sync_type_config={"last_vacuum_version": 41, "last_vacuum_version_cdc": 7})

        run_scheduled, _ = await _run_post_load(schema, _make_helper(), cdc_write_mode="scd2_append")

        run_scheduled.assert_awaited_once_with(schema, is_cdc_companion=True, compact_small_files=False)

    @parameterized.expand([("non_cdc", False), ("cdc", True)])
    @pytest.mark.asyncio
    async def test_prepares_s3_files_with_post_maintenance_file_list(self, _name: str, is_cdc: bool) -> None:
        # Compaction/vacuum maintenance above can rewrite or delete files referenced by the
        # pre-maintenance file_uris snapshot the caller passed in. Regression: prepare_s3_files_for_querying
        # was called with that stale snapshot, raising FileNotFoundError on files maintenance just removed.
        schema = _make_schema(is_cdc=is_cdc)
        post_maintenance_uris = ["s3://bucket/orders/compacted.parquet"]
        helper = _make_helper(file_uris=post_maintenance_uris)

        _, prepare_s3 = await _run_post_load(schema, helper, cdc_write_mode="incremental" if is_cdc else None)

        prepare_s3.assert_awaited_once()
        assert prepare_s3.await_args is not None
        assert prepare_s3.await_args.args[2] == post_maintenance_uris


class TestRegisterTableRowCount:
    @parameterized.expand(
        [
            ("cumulative", True, 10, 40_000_000),
            ("full_refresh_with_rows", False, 10, None),
            ("full_refresh_reporting_zero", False, 0, 40_000_000),
        ]
    )
    @pytest.mark.asyncio
    async def test_passes_the_delta_log_count_when_the_run_count_is_not_the_table_size(
        self, _name: str, cumulative: bool, row_count: int, expected: int | None
    ) -> None:
        # Without the log count, registration counts every published file through chdb or the
        # ClickHouse cluster on each sync of an incremental table.
        schema = _make_schema(is_cdc=False)
        schema.table_row_count_is_cumulative = cumulative
        validate = AsyncMock()

        await _run_post_load(schema, _make_helper(live_row_count=40_000_000), validate=validate, row_count=row_count)

        validate.assert_awaited_once()
        assert validate.await_args is not None
        assert validate.await_args.kwargs["live_row_count"] == expected


_STEP_PHASES = [
    "notify_revenue_analytics",
    "sync_revenue_analytics_views",
    "sync_engineering_analytics_views",
    "maybe_flag_repartition",
]


class TestPostLoadPhaseSummary:
    @parameterized.expand(
        [
            (
                "non_cdc",
                False,
                None,
                ["delta_maintenance", "publish", "list_live_files", "sync_bookkeeping", "register_table"],
            ),
            (
                "cdc",
                True,
                "incremental",
                [
                    "delta_maintenance",
                    "publish",
                    "list_live_files",
                    "sync_bookkeeping",
                    "register_table",
                    "cdc_post_load",
                ],
            ),
            (
                "cdc_companion",
                True,
                "scd2_append",
                ["delta_maintenance", "publish", "list_live_files", "sync_bookkeeping", "cdc_post_load"],
            ),
        ]
    )
    @pytest.mark.asyncio
    async def test_one_summary_line_names_every_post_load_phase(
        self, _name: str, is_cdc: bool, cdc_write_mode: str | None, core_phases: list[str]
    ) -> None:
        logger = MagicMock()
        schema = _make_schema(is_cdc=is_cdc)

        with record_post_load_phases(logger, None, team_id=schema.team_id):
            await _run_post_load(schema, _make_helper(file_uris=["a", "b"]), cdc_write_mode=cdc_write_mode)

        logger.info.assert_called_once()
        assert logger.info.call_args.args == (SUMMARY_EVENT,)
        summary = logger.info.call_args.kwargs
        assert summary["phase_names"] == [*core_phases, *_STEP_PHASES]
        phases = {phase["name"]: phase for phase in summary["phases"]}
        assert phases["list_live_files"]["parent"] == "publish"
        assert phases["list_live_files"]["live_files"] == 2


class TestPublishQueryableFilesDoubleBuffer:
    _STATE = {
        "query_folder_state": {
            "orders__query": {
                "active": "orders__query_a",
                "active_since": "2026-08-19T10:00:00+00:00",
                "active_job_id": "job-1",
                "history_since": "2026-08-19T09:00:00+00:00",
                "inactive_since": {"orders__query_c": "2026-08-19T10:00:00+00:00"},
            }
        }
    }
    _HISTORY = QueryFolderPointerHistory(
        active="orders__query_a",
        active_since=datetime(2026, 8, 19, 10, tzinfo=UTC),
        active_job_id="job-1",
        history_since=datetime(2026, 8, 19, 9, tzinfo=UTC),
        inactive_since={"orders__query_c": datetime(2026, 8, 19, 10, tzinfo=UTC)},
    )

    @parameterized.expand(
        [
            ("with_record", _STATE, _HISTORY),
            ("no_record", None, None),
        ]
    )
    @pytest.mark.asyncio
    async def test_passes_double_buffering_and_the_pointer_history_to_the_publish_step(
        self,
        _name: str,
        stored_config: dict | None,
        expected_history: QueryFolderPointerHistory | None,
    ) -> None:
        schema = _make_schema(is_cdc=False)
        schema.table.queryable_folder = "orders__query_a"

        _, prepare_s3 = await _run_post_load(schema, _make_helper(), stored_sync_type_config=stored_config)

        prepare_s3.assert_awaited_once()
        assert prepare_s3.await_args is not None
        assert prepare_s3.await_args.kwargs["existing_queryable_folder"] == "orders__query_a"
        assert prepare_s3.await_args.kwargs["double_buffer"] is True
        assert prepare_s3.await_args.kwargs["pointer_history"] == expected_history


class TestCdcCompanionSeeding:
    @parameterized.expand(
        [
            # The seed exists for exactly this: the companion starts as the snapshot's rows.
            ("initial_snapshot_seeds", "both", False, None, True),
            # The incident this guards: seeding resets the companion table, so re-running it on a
            # streaming schema throws away every SCD2 version the stream has accumulated. A
            # redelivered final batch reaches post-load with no write mode (the loader's
            # already-processed path), which used to be indistinguishable from an initial load.
            ("streaming_tick_without_write_mode_does_not_reseed", "both", True, None, False),
            ("cdc_only_streaming_tick_does_not_reseed", "cdc_only", True, None, False),
            # A consolidated schema has no companion table to seed.
            ("consolidated_never_seeds", "consolidated", False, None, False),
            # A companion write is the stream appending to the companion, never a reason to reset it.
            ("companion_write_never_seeds", "both", False, "scd2_append", False),
        ]
    )
    @pytest.mark.asyncio
    async def test_seeds_only_on_the_initial_snapshot(
        self,
        _name: str,
        cdc_table_mode: str,
        initial_sync_complete: bool,
        cdc_write_mode: str | None,
        expect_seed: bool,
    ) -> None:
        schema = _make_schema(
            is_cdc=True,
            cdc_table_mode=cdc_table_mode,
            initial_sync_complete=initial_sync_complete,
        )

        with patch(f"{_LOAD_MODULE}._seed_cdc_companion_from_snapshot", AsyncMock()) as seed:
            await _run_post_load(schema, _make_helper(), cdc_write_mode=cdc_write_mode)

        assert seed.await_count == (1 if expect_seed else 0)


class TestZeroRowRunFinalizesBookkeeping:
    @pytest.mark.asyncio
    async def test_no_delta_table_still_sets_initial_sync_complete(self) -> None:
        # A clean run that wrote zero rows creates no delta table. Post-load used to bail before the
        # bookkeeping, so initial_sync_complete never advanced and the schema stayed "completed but
        # not initial-synced" forever. It must be finalized even with no table to register.
        schema = _make_schema(is_cdc=False, initial_sync_complete=False)
        job = MagicMock()
        job.id = uuid.uuid4()
        job.team_id = schema.team_id
        logger = MagicMock(debug=MagicMock(), adebug=AsyncMock())
        helper = MagicMock(get_delta_table=AsyncMock(return_value=None))

        set_complete = AsyncMock()
        with (
            patch(f"{_LOAD_MODULE}.set_initial_sync_complete", set_complete),
            patch(f"{_PIPELINE_SYNC_MODULE}.update_last_synced_at", AsyncMock()) as synced,
        ):
            result = await run_post_load_operations(
                job=job,
                schema=schema,
                source=MagicMock(),
                delta_table_ref=helper,
                row_count=0,
                table_schema_dict={},
                resource_name="subscription_reports",
                logger=logger,
            )

        assert result is None
        set_complete.assert_awaited_once()
        synced.assert_awaited_once()


class TestGetIncrementalFieldValue:
    def _schema(self, incremental_field: str, sync_type: str = ExternalDataSchema.SyncType.INCREMENTAL) -> MagicMock:
        schema = MagicMock()
        schema.sync_type = sync_type
        schema.sync_type_config = {"incremental_field": incremental_field, "incremental_field_type": "integer"}
        schema.incremental_field_type = "integer"
        schema.should_use_incremental_field = sync_type in (
            ExternalDataSchema.SyncType.INCREMENTAL,
            ExternalDataSchema.SyncType.APPEND,
            ExternalDataSchema.SyncType.WEBHOOK,
        )
        return schema

    def test_returns_max_of_configured_column(self):
        table = pa.table({"id": ["a", "b"], "created": [10, 20]})
        assert get_incremental_field_value(self._schema("created"), table) == 20

    def test_missing_column_raises_actionable_error_matched_by_non_retryable_map(self):
        # A label like "created_at" persisted instead of the real field must fail with guidance
        # (not a raw pyarrow KeyError), and the message must keep matching the Any_Source_Errors
        # substring so the schema is paused instead of retrying the same failure forever.
        table = pa.table({"id": ["a"], "created": [10]})

        with pytest.raises(IncrementalFieldMissingFromDataError) as exc_info:
            get_incremental_field_value(self._schema("created_at"), table)

        message = str(exc_info.value)
        assert '"created_at"' in message
        assert "created" in message  # available columns are listed for self-service fixing
        matching_keys = [key for key in Any_Source_Errors if key in message]
        assert matching_keys, "exception message must stay matched by an Any_Source_Errors entry"

    @parameterized.expand(
        [
            ("xmin", ExternalDataSchema.SyncType.XMIN),
            ("cdc", ExternalDataSchema.SyncType.CDC),
        ]
    )
    def test_stale_incremental_field_ignored_for_self_tracking_sync_types(self, _name: str, sync_type: str):
        # xmin/cdc track their cursor outside sync_type_config (xmin_ceiling, cdc_last_log_position).
        # A schema switched from incremental to xmin/cdc keeps the old incremental_field key around,
        # which used to raise IncrementalFieldMissingFromDataError even though this sync type never
        # reads that column.
        table = pa.table({"id": ["a"], "created": [10]})
        schema = self._schema("updated_at", sync_type=sync_type)

        assert get_incremental_field_value(schema, table) is None


class TestUpdateJobRowCount:
    @pytest.mark.asyncio
    async def test_retries_transient_query_wait_timeout_then_succeeds(self):
        # A saturated pgbouncer pool rejects the row-count UPDATE with `query_wait_timeout`; the
        # query never reached Postgres, so retrying it is safe and avoids failing the whole
        # import activity (and redoing the batch pull) over a momentary blip.
        update = MagicMock(side_effect=[OperationalError("query_wait_timeout"), None])
        queryset = MagicMock(update=update)
        logger = MagicMock(adebug=AsyncMock())

        with (
            patch(f"{_LOAD_MODULE}.ExternalDataJob.objects.filter", return_value=queryset),
            patch(f"{_DB_RETRY_MODULE}.close_old_connections") as close,
            patch(f"{_DB_RETRY_MODULE}.time.sleep") as sleep,
        ):
            await update_job_row_count("job-1", 5, logger)

        assert update.call_count == 2
        close.assert_called_once()
        sleep.assert_called_once_with(2)


class TestNotifyRevenueAnalyticsThatSyncHasCompleted:
    @pytest.mark.asyncio
    async def test_retries_transient_operational_error_then_notifies(self):
        # Opening a fresh pooled Postgres connection from the Temporal worker's thread pool can
        # hit a momentary DNS resolution blip; retrying it is safe and avoids silently skipping
        # the "revenue analytics ready" notification over a transient failure.
        attempts = MagicMock(side_effect=[OperationalError("Name or service not known"), True])

        class _RevenueAnalyticsConfig:
            @property
            def enabled(self):
                return attempts()

        source = MagicMock(
            source_type=ExternalDataSourceType.STRIPE, revenue_analytics_config=_RevenueAnalyticsConfig()
        )
        schema = MagicMock()
        schema.name = STRIPE_CHARGE_RESOURCE_NAME
        schema.team.revenue_analytics_config.notified_first_sync = False
        schema.team.all_users_with_access.return_value = []
        logger = MagicMock(aexception=AsyncMock())

        with (
            patch(f"{_DB_RETRY_MODULE}.close_old_connections") as close,
            patch(f"{_DB_RETRY_MODULE}.time.sleep") as sleep,
        ):
            await notify_revenue_analytics_that_sync_has_completed(schema, source, logger)

        assert attempts.call_count == 2
        close.assert_called_once()
        sleep.assert_called_once_with(2)
        assert schema.team.revenue_analytics_config.notified_first_sync is True
        schema.team.revenue_analytics_config.save.assert_called_once()
        logger.aexception.assert_not_called()
