import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import pyarrow as pa

from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import (
    PersonPropertySourceProjection,
)
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


def _projection(key_column: str, *columns: str) -> PersonPropertySourceProjection:
    return PersonPropertySourceProjection(key_column=key_column, columns=frozenset({key_column, *columns}))


@pytest.mark.asyncio
async def test_should_stage_reflects_projection():
    sink = _sink()
    with patch(f"{_MODULE}.person_property_projection_for", return_value=None):
        assert await sink.should_stage() is False

    other = _sink()
    with patch(f"{_MODULE}.person_property_projection_for", return_value=[_projection("distinct_id", "plan")]):
        assert await other.should_stage() is True


@pytest.mark.asyncio
async def test_stage_chunk_writes_only_projected_columns_present_in_table():
    sink = _sink()
    with (
        patch(
            f"{_MODULE}.person_property_projection_for", return_value=[_projection("distinct_id", "plan", "missing")]
        ),
        patch.object(sink, "_get_fs", return_value=MagicMock()),
        patch(f"{_MODULE}.asyncio.to_thread", new=AsyncMock()) as to_thread,
    ):
        await sink.stage_chunk(chunk=0, table=_table())

    to_thread.assert_awaited_once()
    written_table = to_thread.await_args.args[1]
    # Only projected columns that exist in the table are staged; "missing" and "unused" are dropped.
    assert written_table.column_names == ["distinct_id", "plan"]


@pytest.mark.asyncio
async def test_stage_chunk_skips_source_whose_key_column_is_absent():
    # The key column (person identifier) is missing from the table, so the source's property
    # columns must not be staged with no identifier to attach them to.
    sink = _sink()
    with (
        patch(f"{_MODULE}.person_property_projection_for", return_value=[_projection("user_id", "plan")]),
        patch(f"{_MODULE}.asyncio.to_thread", new=AsyncMock()) as to_thread,
    ):
        await sink.stage_chunk(chunk=0, table=_table())

    to_thread.assert_not_awaited()


@pytest.mark.asyncio
async def test_stage_chunk_stages_only_sources_with_key_present():
    # Two sources: one keyed on a present column, one on an absent column. Only the present
    # source's columns are staged; the absent source's mapped column ("seats") is dropped.
    sink = _sink()
    with (
        patch(
            f"{_MODULE}.person_property_projection_for",
            return_value=[_projection("distinct_id", "plan"), _projection("user_id", "seats")],
        ),
        patch.object(sink, "_get_fs", return_value=MagicMock()),
        patch(f"{_MODULE}.asyncio.to_thread", new=AsyncMock()) as to_thread,
    ):
        await sink.stage_chunk(chunk=0, table=_table())

    to_thread.assert_awaited_once()
    written_table = to_thread.await_args.args[1]
    assert written_table.column_names == ["distinct_id", "plan"]
