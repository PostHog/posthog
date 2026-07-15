import time
import asyncio
import threading
import contextvars
from pathlib import Path
from typing import cast

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import pyarrow as pa
import deltalake

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.cdp_producer import CDPProducer
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.delta_table_helper import (
    DeltaTableHelper,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.pipeline import (
    PipelineNonDLT,
    _evolve_schema_or_widen,
    async_iterate,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import (
    SchemaColumnTypeChangedException,
)

_probe: contextvars.ContextVar[str | None] = contextvars.ContextVar("probe", default=None)


@pytest.mark.asyncio
async def test_async_iterate_propagates_contextvars_to_source_thread():
    # Regression: loop.run_in_executor does not propagate contextvars, so
    # logs emitted from inside a source's streaming generator used to lose
    # team_id / workflow_* and get silently dropped from the produce path.
    _probe.set("bound-value")

    def sync_gen():
        yield _probe.get()
        yield _probe.get()

    seen = [item async for item in async_iterate(sync_gen())]

    assert seen == ["bound-value", "bound-value"]


@pytest.mark.asyncio
async def test_async_iterate_context_snapshot_is_isolated_from_generator_mutations():
    _probe.set("outer")

    def sync_gen():
        _probe.set("inner")
        yield _probe.get()

    seen = [item async for item in async_iterate(sync_gen())]

    assert seen == ["inner"]
    # Caller's context is unaffected by mutations inside the generator.
    assert _probe.get() == "outer"


@pytest.mark.asyncio
async def test_async_iterate_context_mutation_persists_across_iterations():
    # The same context snapshot is reused for every iteration, so writes to
    # ContextVars inside one _next() persist into the next. Intentional:
    # matches pre-#46962 single-thread iteration semantics. Pinned here so
    # a future switch to per-iteration copy (e.g. asyncio.to_thread style)
    # becomes a loud test failure rather than a silent behavior change.
    _probe.set("outer")

    def sync_gen():
        _probe.set("inner")
        yield _probe.get()
        yield _probe.get()

    seen = [item async for item in async_iterate(sync_gen())]

    assert seen == ["inner", "inner"]
    assert _probe.get() == "outer"


@pytest.mark.asyncio
async def test_async_iterate_close_runs_when_cancelled_mid_iteration():
    # Regression: reusing the iteration ctx for the finally-block _close
    # caused RuntimeError on cancellation (ctx still entered by the
    # in-flight _next), which skipped iterator.close() and leaked DB /
    # network resources. Using a fresh cleanup_ctx prevents that.
    closed_flag = threading.Event()

    class SlowIterator:
        def __iter__(self):
            return self

        def __next__(self):
            time.sleep(0.5)  # blocks long enough for cancellation to fire
            return 1

        def close(self):
            closed_flag.set()

    async def consume():
        async for _ in async_iterate(SlowIterator()):
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)  # let the first _next actually enter ctx.run
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # close() must have run despite cancellation mid-iteration.
    assert closed_flag.wait(timeout=3.0), "iterator.close() was not called"


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
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.pipeline.cdp_producer_clear_chunks",
        _raise_import_error,
    )

    with pytest.raises(ImportError_, match="Can't connect to MySQL server on"):
        await pipeline.run()

    pipeline._logger.aexception.assert_awaited_once_with("Failed to clean up delta table helper")


def _wedged_local_helper(tmp_path: Path) -> tuple[str, DeltaTableHelper]:
    """A DeltaTableHelper over a local table whose price column is locked to int64."""
    delta_path = str(tmp_path / "table")
    deltalake.write_deltalake(
        delta_path, pa.table({"id": pa.array([1, 2], type=pa.int64()), "price": pa.array([0, 10], type=pa.int64())})
    )
    logger = MagicMock(adebug=AsyncMock(), ainfo=AsyncMock(), awarning=AsyncMock())
    helper = DeltaTableHelper(resource_name="events", job=MagicMock(), logger=logger)
    patch.object(helper, "_get_delta_table_uri", new=AsyncMock(return_value=delta_path)).start()
    patch.object(helper, "_get_credentials", new=MagicMock(return_value={})).start()
    helper.get_delta_table.cache_clear()
    return delta_path, helper


def _webhook_resource(*, webhook_only: bool) -> SourceResponse:
    return SourceResponse(name="events", items=lambda: [], primary_keys=["id"], webhook_only=webhook_only)


@pytest.mark.asyncio
async def test_evolve_schema_or_widen_unwedges_webhook_only_table(tmp_path: Path):
    # The production incident: a webhook-only table locked to int64 can't take the
    # "reset and fully re-sync" advice (handle_reset_or_full_refresh no-ops the reset
    # for it), so the type conflict must be resolved by widening the table in place.
    _, helper = _wedged_local_helper(tmp_path)
    delta_table = await helper.get_delta_table()
    incoming = pa.table({"id": pa.array([3], type=pa.int64()), "price": pa.array([19.99], type=pa.float64())})

    evolved = await _evolve_schema_or_widen(incoming, delta_table, _webhook_resource(webhook_only=True), helper)

    assert evolved.schema.field("price").type == pa.float64()
    assert evolved.column("price").to_pylist() == [19.99]
    refreshed = await helper.get_delta_table()
    assert refreshed is not None
    stored = refreshed.to_pyarrow_table()
    assert stored.schema.field("price").type == pa.float64()
    by_id = dict(zip(stored.column("id").to_pylist(), stored.column("price").to_pylist()))
    assert by_id == {1: 0.0, 2: 10.0}


@pytest.mark.asyncio
async def test_evolve_schema_or_widen_still_raises_for_poll_sources(tmp_path: Path):
    # Poll-based sources keep the fail-fast behavior: reset and re-sync genuinely works
    # for them, and a surprise full-table rewrite mid-sync is not acceptable there.
    delta_path, helper = _wedged_local_helper(tmp_path)
    delta_table = await helper.get_delta_table()
    incoming = pa.table({"id": pa.array([3], type=pa.int64()), "price": pa.array([19.99], type=pa.float64())})

    with pytest.raises(SchemaColumnTypeChangedException):
        await _evolve_schema_or_widen(incoming, delta_table, _webhook_resource(webhook_only=False), helper)

    untouched = deltalake.DeltaTable(delta_path)
    assert untouched.version() == 0
    assert untouched.to_pyarrow_table().schema.field("price").type == pa.int64()
