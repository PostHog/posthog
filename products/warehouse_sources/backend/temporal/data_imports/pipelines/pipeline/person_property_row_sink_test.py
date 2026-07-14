import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import pyarrow as pa

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.person_property_row_sink import (
    PersonPropertyRowSink,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.person_property_row_sink"


def _sink() -> PersonPropertyRowSink:
    logger = MagicMock()
    logger.adebug = AsyncMock()
    return PersonPropertyRowSink(team_id=1, schema_id="schema-1", job_id="job-1", logger=logger)


def _table() -> pa.Table:
    return pa.table({"distinct_id": ["a"], "plan": ["pro"], "seats": [3], "unused": ["x"]})


@pytest.mark.asyncio
async def test_should_stage_reflects_projection():
    sink = _sink()
    with patch(f"{_MODULE}.person_property_projection_for", return_value=None):
        assert await sink.should_stage() is False

    other = _sink()
    with patch(f"{_MODULE}.person_property_projection_for", return_value=["distinct_id", "plan"]):
        assert await other.should_stage() is True


@pytest.mark.asyncio
async def test_stage_chunk_writes_only_projected_columns_present_in_table():
    sink = _sink()
    with (
        patch(f"{_MODULE}.person_property_projection_for", return_value=["distinct_id", "plan", "missing"]),
        patch.object(sink, "_get_fs", return_value=MagicMock()),
        patch(f"{_MODULE}.asyncio.to_thread", new=AsyncMock()) as to_thread,
    ):
        await sink.stage_chunk(chunk=0, table=_table())

    to_thread.assert_awaited_once()
    written_table = to_thread.await_args.args[1]
    # Only projected columns that exist in the table are staged; "missing" and "unused" are dropped.
    assert written_table.column_names == ["distinct_id", "plan"]


@pytest.mark.asyncio
async def test_stage_chunk_is_noop_when_no_projected_columns_present():
    sink = _sink()
    with (
        patch(f"{_MODULE}.person_property_projection_for", return_value=["not_in_table"]),
        patch(f"{_MODULE}.asyncio.to_thread", new=AsyncMock()) as to_thread,
    ):
        await sink.stage_chunk(chunk=0, table=_table())

    to_thread.assert_not_awaited()
