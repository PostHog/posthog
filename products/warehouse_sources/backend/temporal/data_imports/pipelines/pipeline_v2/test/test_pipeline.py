import uuid
from typing import cast

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.cdp_producer import CDPProducer
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v2.pipeline import PipelineNonDLT
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

_PIPELINE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v2.pipeline"


@pytest.mark.asyncio
async def test_run_cleanup_failure_does_not_mask_import_error(monkeypatch):
    # Regression: run()'s finally calls get_delta_table() (object-storage I/O) purely for
    # memory cleanup. When that raised — e.g. a transient object-storage blip — it replaced
    # the in-flight import error, so a connection failure already classified as non-retryable
    # surfaced as the unrelated cleanup error and the job retried to its maximum instead of
    # stopping. The body error must propagate; the cleanup error must be swallowed.
    pipeline = PipelineNonDLT.__new__(PipelineNonDLT)
    pipeline._logger = AsyncMock()
    pipeline._resumable_source_manager = None
    pipeline._cdp_producer = cast(CDPProducer, object())  # unused: the patched clear-chunks ignores it
    pipeline._resource = cast(SourceResponse, object())
    pipeline._delta_table_helper = AsyncMock()
    pipeline._delta_table_helper.get_delta_table.side_effect = OSError("object storage unavailable")

    class ImportError_(Exception):
        pass

    async def _raise_import_error(_cdp_producer):
        raise ImportError_("Can't connect to MySQL server on")

    monkeypatch.setattr(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v2.pipeline.cdp_producer_clear_chunks",
        _raise_import_error,
    )

    with pytest.raises(ImportError_, match="Can't connect to MySQL server on"):
        await pipeline.run()

    pipeline._logger.aexception.assert_awaited_once_with("Failed to clean up delta table helper")


def _make_pipeline_for_post_run_operations() -> PipelineNonDLT:
    pipeline = PipelineNonDLT.__new__(PipelineNonDLT)
    pipeline._logger = AsyncMock()
    pipeline._delta_table_helper = AsyncMock()
    pipeline._delta_table_helper.get_delta_table.return_value = MagicMock()
    pipeline._delta_table_helper.get_file_uris.return_value = []
    pipeline._job = MagicMock(id=uuid.uuid4(), team_id=1)
    pipeline._table = None
    pipeline._resource_name = "orders"
    pipeline._schema = MagicMock()
    pipeline._schema.initial_sync_complete = True
    # Non-CDC skips the CDC-companion-seeding block, so only validate_schema_and_update_table
    # (mocked below) needs to be reachable.
    pipeline._schema.sync_type = ExternalDataSchema.SyncType.INCREMENTAL
    pipeline._schema.cdc_table_mode = "consolidated"
    pipeline._source = MagicMock()
    pipeline._resource = MagicMock()
    pipeline._internal_schema = MagicMock()
    pipeline._last_incremental_field_value = None
    return pipeline


def _fake_database_sync_to_async_pool(fn):
    async def _inner(*args, **kwargs):
        return fn(*args, **kwargs)

    return _inner


class TestPostRunOperationsCompactionErrorHandling:
    # Regression: `_post_run_operations` used to call `capture_exception` for every compaction
    # failure, including transient S3 rate-limit/connectivity blips that are already non-fatal
    # (the sync completes regardless) — flooding error tracking with noise. A genuine compaction
    # bug must still be captured.
    @parameterized.expand(
        [
            ("transient_s3_slowdown", OSError("Generic S3 error: Please reduce your request rate."), False),
            ("genuine_bug", OSError("Access Denied: not authorized"), True),
        ]
    )
    @pytest.mark.asyncio
    async def test_compaction_error_handling(self, _name: str, error: Exception, expect_capture: bool):
        pipeline = _make_pipeline_for_post_run_operations()
        cast(AsyncMock, pipeline._delta_table_helper.compact_table).side_effect = error

        with (
            patch(f"{_PIPELINE_MODULE}.capture_exception") as mock_capture,
            patch(f"{_PIPELINE_MODULE}.database_sync_to_async_pool", _fake_database_sync_to_async_pool),
            patch(f"{_PIPELINE_MODULE}.prepare_s3_files_for_querying", AsyncMock(return_value="orders__query_1")),
            patch(f"{_PIPELINE_MODULE}.update_last_synced_at", AsyncMock()),
            patch(f"{_PIPELINE_MODULE}.notify_revenue_analytics_that_sync_has_completed", AsyncMock()),
            patch(f"{_PIPELINE_MODULE}.finalize_desc_sort_incremental_value", AsyncMock()),
            patch(f"{_PIPELINE_MODULE}.validate_schema_and_update_table", AsyncMock()),
        ):
            await pipeline._post_run_operations(row_count=10)

        assert mock_capture.called is expect_capture
        if expect_capture:
            cast(AsyncMock, pipeline._logger.aexception).assert_awaited_once()
        else:
            cast(AsyncMock, pipeline._logger.awarning).assert_awaited_once()
