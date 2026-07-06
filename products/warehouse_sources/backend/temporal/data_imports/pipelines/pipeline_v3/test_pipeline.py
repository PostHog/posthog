from typing import cast

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline import PipelineV3


def _make_logger() -> MagicMock:
    logger = MagicMock()
    logger.adebug = AsyncMock()
    logger.ainfo = AsyncMock()
    logger.awarning = AsyncMock()
    logger.aerror = AsyncMock()
    logger.exception = MagicMock()
    return logger


def _make_pipeline() -> PipelineV3:
    """Build a PipelineV3 with just enough wiring to exercise run()."""
    with patch.object(PipelineV3, "__init__", return_value=None):
        pipeline = PipelineV3.__new__(PipelineV3)

    pipeline._resource = MagicMock(name="test_table", primary_keys=["id"])
    pipeline._resource_name = "test_table"
    pipeline._job = MagicMock(team_id=1, workflow_run_id="run-abc", billable=False)
    pipeline._source = MagicMock(source_type="Postgres")
    pipeline._schema = MagicMock(
        id="schema-1",
        source_id="source-1",
        is_incremental=False,
        is_webhook=False,
        is_append=False,
        table=None,
    )
    pipeline._table = None
    pipeline._logger = _make_logger()
    pipeline._is_incremental = False
    pipeline._reset_pipeline = False
    pipeline._delta_table_helper = MagicMock(is_first_sync=True)
    pipeline._resumable_source_manager = None
    pipeline._internal_schema = MagicMock()
    pipeline._cdp_producer = MagicMock()
    pipeline._batcher = MagicMock()
    pipeline._load_id = 1
    pipeline._s3_batch_writer = MagicMock()
    pipeline._pg_producer = MagicMock(sync_type="full_refresh")
    pipeline._accumulated_pa_schema = None
    pipeline._batch_results = []
    pipeline._shutdown_monitor = MagicMock()
    pipeline._attempt = 1
    pipeline._uses_delta_write_column_selection = False
    pipeline._observed_columns = {}

    return pipeline


class TestAttemptScopedRunUuid:
    def test_run_uuid_includes_attempt_number(self) -> None:
        mock_job = MagicMock(
            team_id=1,
            workflow_run_id="wfrun-abc",
            billable=False,
            id="job-1",
        )
        mock_schema = MagicMock(
            id="schema-1",
            source_id="source-1",
            is_incremental=False,
            is_webhook=False,
            is_xmin=False,
            is_append=False,
            table=None,
            primary_key_columns=None,
            partition_count=None,
            partition_size=None,
            partitioning_keys=None,
            partition_format=None,
            partition_mode=None,
            incremental_field_earliest_value=None,
            incremental_field_type=None,
        )
        mock_source = MagicMock()
        mock_resource = MagicMock(
            name="test",
            primary_keys=["id"],
            partition_count=None,
            partition_size=None,
            partition_keys=None,
            partition_format=None,
            partition_mode=None,
        )

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.current_activity_attempt",
                return_value=3,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.current_workflow_id",
                return_value="wf-1",
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.current_workflow_run_id",
                return_value="wfrun-abc",
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.S3BatchWriter",
            ) as mock_s3_writer_cls,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.PostgresProducer",
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.DeltaTableHelper"
            ),
        ):
            mock_s3_writer_cls.return_value = MagicMock(get_run_uuid=MagicMock(return_value="wfrun-abc-a3"))
            pipeline: PipelineV3 = PipelineV3(
                source_response=mock_resource,
                logger=_make_logger(),
                job_id="job-1",
                reset_pipeline=False,
                shutdown_monitor=MagicMock(),
                job=mock_job,
                schema=mock_schema,
                source=mock_source,
                table=None,
                resumable_source_manager=None,
            )

        assert pipeline._attempt == 3
        mock_s3_writer_cls.assert_called_once()
        assert mock_s3_writer_cls.call_args[0][3] == "wfrun-abc-a3"

    @pytest.mark.asyncio
    async def test_skips_reset_table_on_retry(self) -> None:
        pipeline = _make_pipeline()
        pipeline._attempt = 2
        pipeline._reset_pipeline = True
        pipeline._cdp_producer = MagicMock(should_produce_table=AsyncMock(return_value=False))

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.cdp_producer_clear_chunks",
                new_callable=AsyncMock,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.reset_rows_synced_if_needed",
                new_callable=AsyncMock,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.validate_incremental_sync",
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.setup_row_tracking_with_billing_check",
                new_callable=AsyncMock,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.handle_reset_or_full_refresh",
                new_callable=AsyncMock,
            ) as mock_reset,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.activity",
            ) as mock_activity,
        ):
            mock_activity.in_activity.return_value = False
            pipeline._resource.items = MagicMock(return_value=iter([]))
            pipeline._batcher.should_yield.return_value = False  # type: ignore[attr-defined]

            await pipeline.run()

        mock_reset.assert_not_called()


class TestExtractionFailureDoesNotCleanupS3:
    @pytest.mark.asyncio
    async def test_s3_files_preserved_when_extraction_fails(self) -> None:
        pipeline = _make_pipeline()
        s3_writer = cast(MagicMock, pipeline._s3_batch_writer)

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.cdp_producer_clear_chunks",
                side_effect=RuntimeError("simulated extraction failure"),
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.activity"
            ) as mock_activity,
        ):
            mock_activity.in_activity.return_value = False

            with pytest.raises(RuntimeError, match="simulated extraction failure"):
                await pipeline.run()

        s3_writer.cleanup.assert_not_called()
