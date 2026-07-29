from typing import cast

import pytest
from unittest.mock import AsyncMock

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.cdp_producer import CDPProducer
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v2.pipeline import PipelineNonDLT
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse


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
