import uuid
from typing import cast

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v2.pipeline import PipelineNonDLT
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

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
