import uuid

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
    run_post_load_operations,
    update_job_row_count,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.maintenance import DeltaMaintenance

_LOAD_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.common.load"
_DB_RETRY_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.common.db_retry"
_PIPELINE_SYNC_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_sync"
_REPARTITION_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.repartition_controller"


def _make_schema(*, is_cdc: bool, sync_type_config: dict | None = None, partition_count: int | None = 7) -> MagicMock:
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
    schema.cdc_table_mode = "consolidated"
    schema.initial_sync_complete = True
    return schema


def _make_helper(*, file_uris: list[str] | None = None) -> MagicMock:
    return MagicMock(
        get_delta_table=AsyncMock(return_value=MagicMock()),
        get_file_uris=AsyncMock(return_value=file_uris or []),
    )


async def _run_post_load(
    schema: MagicMock,
    helper: MagicMock,
    *,
    cdc_write_mode: str | None = None,
    compact_error: Exception | None = None,
) -> tuple[AsyncMock, AsyncMock, AsyncMock]:
    job = MagicMock()
    job.id = uuid.uuid4()
    job.team_id = schema.team_id
    logger = MagicMock(adebug=AsyncMock(), ainfo=AsyncMock())

    prepare_s3 = AsyncMock(return_value="orders__query_1")
    run_scheduled = AsyncMock()
    compact_table = AsyncMock(side_effect=compact_error)
    with (
        patch(f"{_LOAD_MODULE}.prepare_s3_files_for_querying", prepare_s3),
        patch(f"{_LOAD_MODULE}.notify_revenue_analytics_that_sync_has_completed", AsyncMock()),
        patch(f"{_LOAD_MODULE}.sync_revenue_analytics_views", MagicMock()),
        patch(f"{_LOAD_MODULE}.DataWarehouseTable", MagicMock()),
        patch.object(DeltaMaintenance, "run_scheduled", run_scheduled),
        patch.object(DeltaMaintenance, "compact_table", compact_table),
        patch(f"{_PIPELINE_SYNC_MODULE}.update_last_synced_at", AsyncMock()),
        patch(f"{_PIPELINE_SYNC_MODULE}.validate_schema_and_update_table", AsyncMock()),
        patch(f"{_PIPELINE_SYNC_MODULE}.register_cdc_companion_table", AsyncMock()),
        patch(f"{_REPARTITION_MODULE}.maybe_flag_for_repartition", AsyncMock()),
    ):
        await run_post_load_operations(
            job=job,
            schema=schema,
            source=MagicMock(),
            delta_table_helper=helper,
            row_count=10,
            table_schema_dict={},
            resource_name="orders",
            logger=logger,
            cdc_write_mode=cdc_write_mode,
        )
    return run_scheduled, compact_table, prepare_s3


class TestRunPostLoadDeltaMaintenance:
    """Post-load picks the right maintenance flavor per schema kind; the threshold/watermark
    mechanics themselves are covered in core/delta/test/test_maintenance.py."""

    @pytest.mark.asyncio
    async def test_cdc_schema_uses_threshold_maintenance_not_unconditional_compact(self):
        # The incident behavior this guards: CDC finals land every tick, so an unconditional
        # compact_table here means hundreds of compact+vacuum cycles per hour on a busy source.
        schema = _make_schema(is_cdc=True, sync_type_config={"last_vacuum_version": 41})

        run_scheduled, compact_table, _ = await _run_post_load(schema, _make_helper(), cdc_write_mode="incremental")

        compact_table.assert_not_awaited()
        run_scheduled.assert_awaited_once_with(schema, is_cdc_companion=False)

    @pytest.mark.asyncio
    async def test_non_cdc_schema_keeps_unconditional_compact(self):
        schema = _make_schema(is_cdc=False)

        run_scheduled, compact_table, _ = await _run_post_load(schema, _make_helper())

        compact_table.assert_awaited_once()
        run_scheduled.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cdc_companion_write_runs_companion_maintenance(self):
        # The snapshot and _cdc companion are different delta tables, so a companion (scd2_append)
        # write must run maintenance in companion mode — run_scheduled then uses the companion's own
        # watermark key and layout instead of the snapshot's (see test_maintenance.TestRunScheduled).
        schema = _make_schema(is_cdc=True, sync_type_config={"last_vacuum_version": 41, "last_vacuum_version_cdc": 7})

        run_scheduled, _, _ = await _run_post_load(schema, _make_helper(), cdc_write_mode="scd2_append")

        run_scheduled.assert_awaited_once_with(schema, is_cdc_companion=True)

    @parameterized.expand([("non_cdc", False), ("cdc", True)])
    @pytest.mark.asyncio
    async def test_prepares_s3_files_with_post_maintenance_file_list(self, _name: str, is_cdc: bool) -> None:
        # Compaction/vacuum maintenance above can rewrite or delete files referenced by the
        # pre-maintenance file_uris snapshot the caller passed in. Regression: prepare_s3_files_for_querying
        # was called with that stale snapshot, raising FileNotFoundError on files maintenance just removed.
        schema = _make_schema(is_cdc=is_cdc)
        post_maintenance_uris = ["s3://bucket/orders/compacted.parquet"]
        helper = _make_helper(file_uris=post_maintenance_uris)

        _, _, prepare_s3 = await _run_post_load(schema, helper, cdc_write_mode="incremental" if is_cdc else None)

        prepare_s3.assert_awaited_once()
        assert prepare_s3.await_args is not None
        assert prepare_s3.await_args.args[2] == post_maintenance_uris

    @parameterized.expand(
        [
            # A genuine compaction bug must still be captured for visibility.
            ("genuine_bug", RuntimeError("compaction blew up"), True),
            # A transient S3 rate-limit/connectivity blip is already non-fatal here (the next
            # sync's maintenance retries the same idempotent cleanup) and must not be promoted
            # into a fresh error-tracking issue — the regression this guards.
            ("transient_s3_slowdown", OSError("Generic S3 error: Please reduce your request rate."), False),
        ]
    )
    @pytest.mark.asyncio
    async def test_compact_failure_handling(self, _name: str, error: Exception, expect_capture: bool):
        # A compaction hiccup must not fail the final batch — the rest of post-load
        # (queryable folder prep, table registration) still has to run or the job wedges.
        schema = _make_schema(is_cdc=False)

        with patch(f"{_LOAD_MODULE}.capture_exception") as mock_capture:
            _, _, prepare_s3 = await _run_post_load(schema, _make_helper(), compact_error=error)

        assert mock_capture.called is expect_capture
        prepare_s3.assert_awaited_once()


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
