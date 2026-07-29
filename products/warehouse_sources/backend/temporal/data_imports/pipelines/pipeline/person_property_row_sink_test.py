from datetime import UTC, datetime, timedelta

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import pyarrow as pa

from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import (
    PersonPropertySourceProjection,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.person_property_row_sink import (
    ABANDONED_STAGED_PREFIX_TTL,
    PersonPropertyRowSink,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.person_property_row_sink"


def _sink(is_incremental: bool = False) -> PersonPropertyRowSink:
    logger = MagicMock()
    logger.adebug = AsyncMock()
    return PersonPropertyRowSink(
        team_id=1, schema_id="schema-1", job_id="job-1", logger=logger, is_incremental=is_incremental
    )


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
    assert to_thread.await_args is not None
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
    assert to_thread.await_args is not None
    written_table = to_thread.await_args.args[1]
    assert written_table.column_names == ["distinct_id", "plan"]


class _FakeS3ClientCM:
    def __init__(self, s3_client):
        self._s3_client = s3_client

    async def __aenter__(self):
        return self._s3_client

    async def __aexit__(self, *exc):
        return False


def _s3_client(find_result=None) -> MagicMock:
    s3_client = MagicMock()
    s3_client._rm = AsyncMock()
    s3_client._find = AsyncMock(return_value=find_result if find_result is not None else {})
    return s3_client


@pytest.mark.asyncio
async def test_clear_chunks_keeps_fresh_sibling_prefixes_and_sweeps_abandoned_ones():
    # A fresh sibling prefix belongs to a consumer that is merely lagging — deleting it loses an
    # incremental sync's staged delta for good. Only long-abandoned prefixes may be swept.
    sink = _sink()
    schema_prefix = sink._get_schema_prefix()
    fresh_file = f"{schema_prefix}/job-recent/chunk_0.parquet"
    stale_file = f"{schema_prefix}/job-old/chunk_0.parquet"
    now = datetime.now(UTC)
    s3_client = _s3_client(
        find_result={
            fresh_file: {"LastModified": now - timedelta(hours=1)},
            stale_file: {"LastModified": now - ABANDONED_STAGED_PREFIX_TTL - timedelta(days=1)},
        }
    )

    with patch(f"{_MODULE}.aget_s3_client", return_value=_FakeS3ClientCM(s3_client)):
        await sink.clear_chunks()

    removed = [call.args[0] for call in s3_client._rm.await_args_list]
    assert f"s3://{sink._get_path_prefix()}/" in removed  # own job prefix cleared on full refresh
    assert [f"s3://{stale_file}"] in removed  # abandoned sibling swept
    assert all(fresh_file not in str(args) for args in removed)  # lagging sibling survives


@pytest.mark.asyncio
async def test_clear_chunks_keeps_own_prefix_on_incremental_syncs():
    # An incremental retry resumes past the committed cursor, so the failed attempt's staged
    # files are the only record of those rows — clearing the job prefix would lose them for good.
    sink = _sink(is_incremental=True)
    stale_file = f"{sink._get_schema_prefix()}/job-old/chunk_0.parquet"
    s3_client = _s3_client(
        find_result={stale_file: {"LastModified": datetime.now(UTC) - ABANDONED_STAGED_PREFIX_TTL - timedelta(days=1)}}
    )

    with patch(f"{_MODULE}.aget_s3_client", return_value=_FakeS3ClientCM(s3_client)):
        await sink.clear_chunks()

    removed = [call.args[0] for call in s3_client._rm.await_args_list]
    assert f"s3://{sink._get_path_prefix()}/" not in removed  # own prefix survives the retry
    assert [f"s3://{stale_file}"] in removed  # the abandoned-sibling backstop still runs


@pytest.mark.asyncio
async def test_stage_chunk_filenames_are_unique_per_attempt():
    # A retried incremental attempt restarts chunk indices at 0 while its predecessor's rows are
    # never re-extracted; identical filenames would overwrite (and lose) the earlier staging.
    paths = []
    for attempt in (_sink(is_incremental=True), _sink(is_incremental=True)):
        attempt._attempt_token = str(id(attempt))  # distinct per attempt, as wall-clock time is
        with (
            patch(f"{_MODULE}.person_property_projection_for", return_value=[_projection("distinct_id", "plan")]),
            patch.object(attempt, "_get_fs", return_value=MagicMock()),
            patch(f"{_MODULE}.asyncio.to_thread", new=AsyncMock()) as to_thread,
        ):
            await attempt.stage_chunk(chunk=0, table=_table())
        assert to_thread.await_args is not None
        paths.append(to_thread.await_args.args[2])

    assert len(set(paths)) == 2


@pytest.mark.asyncio
async def test_clear_chunks_tolerates_missing_prefixes():
    # First sync of a schema has nothing staged anywhere; clearing must not fail the sync.
    sink = _sink()
    s3_client = _s3_client()
    s3_client._rm = AsyncMock(side_effect=FileNotFoundError)
    s3_client._find = AsyncMock(side_effect=FileNotFoundError)

    with patch(f"{_MODULE}.aget_s3_client", return_value=_FakeS3ClientCM(s3_client)):
        await sink.clear_chunks()
