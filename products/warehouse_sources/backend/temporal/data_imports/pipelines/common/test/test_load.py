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
_REPARTITION_MODULE = (
    "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.repartition_controller"
)


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
            file_uris=["s3://bucket/orders/1.parquet"],
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

    @pytest.mark.asyncio
    async def test_maintenance_failure_does_not_fail_post_load(self):
        # A maintenance hiccup (S3 flake) must not fail the final batch — the rest of post-load
        # (queryable folder prep, table registration) still has to run or the job wedges.
        schema = _make_schema(is_cdc=True)
        helper = _make_helper()
        helper.run_maintenance = AsyncMock(side_effect=RuntimeError("maintenance blew up"))

        with patch(f"{_LOAD_MODULE}.capture_exception") as mock_capture:
            _, prepare_s3 = await _run_post_load(schema, helper, cdc_write_mode="incremental")

        mock_capture.assert_called_once()
        prepare_s3.assert_awaited_once()


class TestGetIncrementalFieldValue:
    def _schema(self, incremental_field: str) -> MagicMock:
        schema = MagicMock()
        schema.sync_type = ExternalDataSchema.SyncType.INCREMENTAL
        schema.sync_type_config = {"incremental_field": incremental_field, "incremental_field_type": "integer"}
        schema.incremental_field_type = "integer"
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
