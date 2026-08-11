import uuid
from typing import cast

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v2.pipeline import PipelineNonDLT
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.import_data_sync import (
    ImportJobModels,
)

_PIPELINE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v2.pipeline"


@pytest.mark.asyncio
async def test_run_cleanup_does_not_call_get_delta_table_and_does_not_mask_import_error():
    # Regression: run()'s finally used to call get_delta_table() (object-storage I/O) purely for
    # memory cleanup, even on a run that failed before ever fetching a delta table (nothing
    # cached, nothing to clean up). A transient object-storage blip on that spurious call then
    # replaced the in-flight import error, so a failure already classified as non-retryable
    # surfaced as the unrelated cleanup error and the job retried to its maximum instead of
    # stopping. Cleanup must pop whatever's cached instead of recomputing it, so it can no
    # longer make its own object-storage call at all.
    pipeline = PipelineNonDLT.__new__(PipelineNonDLT)
    pipeline._logger = AsyncMock()
    pipeline._resumable_source_manager = None
    pipeline._resource = cast(SourceResponse, object())
    delta_table_ref = AsyncMock()
    delta_table_ref.get_delta_table.cache_pop.return_value = None
    pipeline._delta_table_ref = delta_table_ref

    class ImportError_(Exception):
        pass

    pipeline._sinks = MagicMock(clear=AsyncMock(side_effect=ImportError_("Can't connect to MySQL server on")))

    with pytest.raises(ImportError_, match="Can't connect to MySQL server on"):
        await pipeline.run()

    # run()'s finally `del self._delta_table_ref`s afterward, so assert on the captured
    # reference rather than re-reading it off `pipeline`.
    delta_table_ref.get_delta_table.assert_not_called()
    delta_table_ref.get_delta_table.cache_pop.assert_called_once_with(delta_table_ref)


@pytest.mark.asyncio
async def test_post_run_operations_routes_through_shared_post_load():
    # The e2e tests mock `_post_run_operations`, so nothing else notices if this wrapper stops
    # returning the orchestrator's queryable folder (ducklake registration silently loses
    # `prepared_queryable_folder`) or stops forwarding the resource and last incremental value
    # (desc-sort cursor finalization silently skips).
    pipeline = PipelineNonDLT.__new__(PipelineNonDLT)
    pipeline._logger = AsyncMock()
    pipeline._delta_table_ref = AsyncMock()
    pipeline._job = MagicMock(id=uuid.uuid4(), team_id=1)
    pipeline._resource_name = "orders"
    pipeline._schema = MagicMock()
    pipeline._source = MagicMock()
    pipeline._resource = MagicMock()
    pipeline._internal_schema = MagicMock()
    pipeline._last_incremental_field_value = 5

    post_load = AsyncMock(return_value="orders__query_2")
    with patch(f"{_PIPELINE_MODULE}.run_post_load_operations", post_load):
        result = await pipeline._post_run_operations(row_count=10)

    assert result == "orders__query_2"
    assert post_load.await_args is not None
    kwargs = post_load.await_args.kwargs
    assert kwargs["resource"] is pipeline._resource
    assert kwargs["last_incremental_field_value"] == 5
    assert kwargs["row_count"] == 10


class TestDeltaTableRefFirstSyncWiring:
    @parameterized.expand(
        [
            ("no_table_row_yet", None, True),
            ("table_row_already_exists", MagicMock(), False),
        ]
    )
    def test_is_first_sync_matches_whether_a_table_row_exists(
        self, _name: str, table: MagicMock | None, expected_is_first_sync: bool
    ) -> None:
        # Regression: a schema with no DataWarehouseTable row yet is treated as a first sync by
        # `validate_incremental_sync` (which skips the primary-key requirement), but the writer's
        # own first-sync detection only fires when no Delta table physically exists in storage.
        # If a Delta table happens to already exist there (e.g. left over from an earlier attempt
        # at this same first sync), those two checks used to disagree and the writer wrongly took
        # the merge path, raising MissingPrimaryKeysException on a keyless incremental table that
        # `validate_incremental_sync` had just waved through. The `DeltaTableRef` must be
        # constructed with `is_first_sync` set from the same `table is None` check.
        mock_job = MagicMock(team_id=1)
        mock_schema = MagicMock(
            id="schema-1",
            name="orders",
            is_incremental=True,
            is_webhook=False,
            is_xmin=False,
            incremental_field_earliest_value=None,
            incremental_field_type=None,
        )
        mock_source = MagicMock(source_type="Redshift")
        mock_resource = MagicMock(name="orders", chunk_size=None, chunk_size_bytes=None)

        with (
            patch(f"{_PIPELINE_MODULE}.resolve_primary_keys", return_value=None),
            patch(f"{_PIPELINE_MODULE}.Batcher"),
            patch(f"{_PIPELINE_MODULE}.HogQLSchema"),
            patch(f"{_PIPELINE_MODULE}.build_pipeline_sinks"),
            patch(f"{_PIPELINE_MODULE}.source_uses_delta_write_column_selection", return_value=False),
            patch(f"{_PIPELINE_MODULE}.DeltaTableRef") as mock_delta_table_ref_cls,
        ):
            PipelineNonDLT(
                source_response=mock_resource,
                logger=MagicMock(),
                job_id="job-1",
                reset_pipeline=False,
                shutdown_monitor=MagicMock(),
                resumable_source_manager=None,
                models=ImportJobModels(job=mock_job, schema=mock_schema, source=mock_source, table=table),
            )

        assert mock_delta_table_ref_cls.call_args.kwargs["is_first_sync"] is expected_is_first_sync
