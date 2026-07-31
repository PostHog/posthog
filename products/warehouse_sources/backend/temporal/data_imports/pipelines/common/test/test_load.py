import uuid

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import pyarrow as pa
from parameterized import parameterized

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.external_data_job import Any_Source_Errors
from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.load import (
    IncrementalFieldMissingFromDataError,
    get_incremental_field_value,
    run_post_load_operations,
)

_LOAD_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.common.load"
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


def _make_helper(*, run_maintenance_returns: int | None = None, file_uris: list[str] | None = None) -> MagicMock:
    return MagicMock(
        get_delta_table=AsyncMock(return_value=MagicMock()),
        get_file_uris=AsyncMock(return_value=file_uris or []),
        compact_table=AsyncMock(),
        run_maintenance=AsyncMock(return_value=run_maintenance_returns),
    )


async def _run_post_load(
    schema: MagicMock,
    helper: MagicMock,
    *,
    cdc_write_mode: str | None = None,
) -> tuple[MagicMock, AsyncMock]:
    job = MagicMock()
    job.id = uuid.uuid4()
    job.team_id = schema.team_id
    logger = MagicMock(adebug=AsyncMock(), ainfo=AsyncMock())

    prepare_s3 = AsyncMock(return_value="orders__query_1")
    with (
        patch(f"{_LOAD_MODULE}.prepare_s3_files_for_querying", prepare_s3),
        patch(f"{_LOAD_MODULE}.notify_revenue_analytics_that_sync_has_completed", AsyncMock()),
        patch(f"{_LOAD_MODULE}.sync_revenue_analytics_views", MagicMock()),
        patch(f"{_LOAD_MODULE}.update_sync_type_config_keys", MagicMock()) as update_config,
        patch(f"{_LOAD_MODULE}.DataWarehouseTable", MagicMock()),
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
    return update_config, prepare_s3


class TestRunPostLoadDeltaMaintenance:
    @pytest.mark.asyncio
    async def test_cdc_schema_uses_threshold_maintenance_not_unconditional_compact(self):
        # The incident behavior this guards: CDC finals land every tick, so an unconditional
        # compact_table here means hundreds of compact+vacuum cycles per hour on a busy source.
        schema = _make_schema(is_cdc=True, sync_type_config={"last_vacuum_version": 41})
        helper = _make_helper()

        await _run_post_load(schema, helper, cdc_write_mode="incremental")

        helper.compact_table.assert_not_awaited()
        assert helper.run_maintenance.await_args is not None
        assert helper.run_maintenance.await_args.kwargs == {
            "partition_count": 7,
            "last_vacuum_version": 41,
            "commit_threshold": 100,
        }

    @pytest.mark.asyncio
    async def test_missing_partition_count_is_derived_from_table_layout(self):
        # datetime/numerical-partitioned schemas persist no partition_count. Passing None through
        # makes the threshold math treat the table as one partition, so any >200-file table would
        # compact every tick again — the exact behavior this change removes.
        schema = _make_schema(is_cdc=True, partition_count=None)
        helper = _make_helper(
            file_uris=[
                "s3://bucket/orders/_ph_partition_key=2026-01/a.parquet",
                "s3://bucket/orders/_ph_partition_key=2026-01/b.parquet",
                "s3://bucket/orders/_ph_partition_key=2026-02/c.parquet",
            ]
        )

        await _run_post_load(schema, helper, cdc_write_mode="incremental")

        assert helper.run_maintenance.await_args is not None
        assert helper.run_maintenance.await_args.kwargs["partition_count"] == 2

    @pytest.mark.asyncio
    async def test_non_cdc_schema_keeps_unconditional_compact(self):
        schema = _make_schema(is_cdc=False)
        helper = _make_helper()

        update_config, _ = await _run_post_load(schema, helper)

        helper.compact_table.assert_awaited_once()
        helper.run_maintenance.assert_not_awaited()
        update_config.assert_not_called()

    @pytest.mark.asyncio
    async def test_cdc_companion_uses_its_own_watermark_key(self):
        # The snapshot and _cdc companion are different delta tables with unrelated versions, so
        # the companion must run cadence maintenance against last_vacuum_version_cdc — reading or
        # writing the snapshot's last_vacuum_version would corrupt both cadences, and skipping
        # cadence maintenance entirely would let companion tombstones accumulate until the
        # file-count thresholds happen to trip. Partition count is derived from its own layout —
        # schema.partition_count describes the snapshot table.
        schema = _make_schema(is_cdc=True, sync_type_config={"last_vacuum_version": 41, "last_vacuum_version_cdc": 7})
        helper = _make_helper(run_maintenance_returns=9, file_uris=["s3://bucket/orders_cdc/a.parquet"])

        update_config, _ = await _run_post_load(schema, helper, cdc_write_mode="scd2_append")

        assert helper.run_maintenance.await_args is not None
        assert helper.run_maintenance.await_args.kwargs == {
            "partition_count": 1,
            "last_vacuum_version": 7,
            "commit_threshold": 100,
        }
        update_config.assert_called_once_with(schema.id, schema.team_id, updates={"last_vacuum_version_cdc": 9})

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
    async def test_watermark_persistence(self, _name: str, returned_version: int | None, expect_write: bool):
        schema = _make_schema(is_cdc=True, sync_type_config={"last_vacuum_version": 41})
        helper = _make_helper(run_maintenance_returns=returned_version)

        update_config, _ = await _run_post_load(schema, helper, cdc_write_mode="incremental")

        if expect_write:
            update_config.assert_called_once_with(
                schema.id, schema.team_id, updates={"last_vacuum_version": returned_version}
            )
        else:
            update_config.assert_not_called()

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

    @parameterized.expand(
        [
            # A genuine maintenance bug must still be captured for visibility.
            ("genuine_bug", RuntimeError("maintenance blew up"), True),
            # A transient S3 rate-limit/connectivity blip is already non-fatal here (the next
            # tick's maintenance retries the same idempotent cleanup) and must not be promoted
            # into a fresh error-tracking issue — the regression this guards.
            ("transient_s3_slowdown", OSError("Generic S3 error: Please reduce your request rate."), False),
        ]
    )
    @pytest.mark.asyncio
    async def test_maintenance_failure_handling(self, _name: str, error: Exception, expect_capture: bool):
        # A maintenance hiccup must not fail the final batch — the rest of post-load
        # (queryable folder prep, table registration) still has to run or the job wedges.
        schema = _make_schema(is_cdc=True)
        helper = _make_helper()
        helper.run_maintenance = AsyncMock(side_effect=error)

        with patch(f"{_LOAD_MODULE}.capture_exception") as mock_capture:
            _, prepare_s3 = await _run_post_load(schema, helper, cdc_write_mode="incremental")

        assert mock_capture.called is expect_capture
        prepare_s3.assert_awaited_once()

    @parameterized.expand(
        [
            ("genuine_bug", RuntimeError("compaction blew up"), True),
            ("transient_s3_slowdown", OSError("Generic S3 error: Please reduce your request rate."), False),
        ]
    )
    @pytest.mark.asyncio
    async def test_compact_failure_handling(self, _name: str, error: Exception, expect_capture: bool):
        # Same non-fatal handling as maintenance, for the non-CDC unconditional compact_table path.
        schema = _make_schema(is_cdc=False)
        helper = _make_helper()
        helper.compact_table = AsyncMock(side_effect=error)

        with patch(f"{_LOAD_MODULE}.capture_exception") as mock_capture:
            _, prepare_s3 = await _run_post_load(schema, helper)

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
