from datetime import UTC, datetime, timedelta

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.conf import settings
from django.db import OperationalError

import pyarrow as pa
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import (
    PersonPropertySourceProjection,
    WarehouseBinding,
    saved_query_binding,
    schema_binding,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.person_property_row_sink import (
    ABANDONED_STAGED_PREFIX_TTL,
    PersonPropertyRowSink,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.person_property_row_sink"


def _sink(is_incremental: bool = False, binding: WarehouseBinding | None = None) -> PersonPropertyRowSink:
    logger = MagicMock()
    logger.adebug = AsyncMock()
    return PersonPropertyRowSink(
        team_id=1,
        binding=binding or schema_binding("schema-1"),
        job_id="job-1",
        logger=logger,
        is_incremental=is_incremental,
    )


def _table() -> pa.Table:
    return pa.table({"distinct_id": ["a"], "plan": ["pro"], "seats": [3], "unused": ["x"]})


def _projection(key_column: str, *columns: str) -> PersonPropertySourceProjection:
    return PersonPropertySourceProjection(key_column=key_column, columns=frozenset({key_column, *columns}))


@pytest.mark.asyncio
async def test_should_run_reflects_projection():
    sink = _sink()
    with patch(f"{_MODULE}.person_property_projection_for", return_value=None):
        assert await sink.should_run() is False

    other = _sink()
    with patch(f"{_MODULE}.person_property_projection_for", return_value=[_projection("distinct_id", "plan")]):
        assert await other.should_run() is True


@pytest.mark.asyncio
async def test_should_run_retries_once_on_a_transient_db_connection_drop():
    # A long-lived Temporal worker's pooled app-DB connection can go stale (pooler recycle,
    # failover, deploy) between syncs. Without a retry, that one-off OperationalError would
    # propagate and get treated as "no person-property mapping to sync" for the whole run instead
    # of the transient blip it is.
    sink = _sink()
    projection = [_projection("distinct_id", "plan")]
    resolver = MagicMock(side_effect=[OperationalError("server closed the connection unexpectedly"), projection])

    with patch(f"{_MODULE}.person_property_projection_for", resolver):
        assert await sink.should_run() is True

    assert resolver.call_count == 2


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
async def test_clear_keeps_fresh_sibling_prefixes_and_sweeps_abandoned_ones():
    # A fresh sibling prefix belongs to a consumer that is merely lagging — deleting it loses an
    # incremental sync's staged delta for good. Only long-abandoned prefixes may be swept.
    sink = _sink()
    binding_prefix = sink._get_binding_prefix()
    fresh_file = f"{binding_prefix}/job-recent/chunk_0.parquet"
    stale_file = f"{binding_prefix}/job-old/chunk_0.parquet"
    now = datetime.now(UTC)
    s3_client = _s3_client(
        find_result={
            fresh_file: {"LastModified": now - timedelta(hours=1)},
            stale_file: {"LastModified": now - ABANDONED_STAGED_PREFIX_TTL - timedelta(days=1)},
        }
    )

    with patch(f"{_MODULE}.aget_s3_client", return_value=_FakeS3ClientCM(s3_client)):
        await sink.clear()

    removed = [call.args[0] for call in s3_client._rm.await_args_list]
    assert f"s3://{sink._get_path_prefix()}/" in removed  # own job prefix cleared on full refresh
    assert [f"s3://{stale_file}"] in removed  # abandoned sibling swept
    assert all(fresh_file not in str(args) for args in removed)  # lagging sibling survives


@pytest.mark.asyncio
async def test_clear_keeps_own_prefix_on_incremental_syncs():
    # An incremental retry resumes past the committed cursor, so the failed attempt's staged
    # files are the only record of those rows — clearing the job prefix would lose them for good.
    sink = _sink(is_incremental=True)
    stale_file = f"{sink._get_binding_prefix()}/job-old/chunk_0.parquet"
    s3_client = _s3_client(
        find_result={stale_file: {"LastModified": datetime.now(UTC) - ABANDONED_STAGED_PREFIX_TTL - timedelta(days=1)}}
    )

    with patch(f"{_MODULE}.aget_s3_client", return_value=_FakeS3ClientCM(s3_client)):
        await sink.clear()

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


@parameterized.expand([("local_setup", True), ("non_local_setup", False)])
def test_get_fs_reuses_the_same_filesystem_across_calls(_name, use_local_setup):
    # stage_chunk() calls _get_fs() once per chunk over a whole sync (potentially thousands of
    # chunks); constructing a fresh S3FileSystem per call leaks its underlying connections/file
    # descriptors until the process runs out of them. Both branches build their own S3FileSystem,
    # so both must cache it.
    sink = _sink()

    with (
        patch.object(settings, "USE_LOCAL_SETUP", use_local_setup),
        patch(f"{_MODULE}.pa_fs.S3FileSystem") as mock_s3_filesystem,
        patch(f"{_MODULE}.ensure_bucket_exists"),
    ):
        first = sink._get_fs()
        second = sink._get_fs()

    mock_s3_filesystem.assert_called_once()
    assert first is second


@pytest.mark.asyncio
async def test_clear_tolerates_missing_prefixes():
    # First sync of a schema has nothing staged anywhere; clearing must not fail the sync.
    sink = _sink()
    s3_client = _s3_client()
    s3_client._rm = AsyncMock(side_effect=FileNotFoundError)
    s3_client._find = AsyncMock(side_effect=FileNotFoundError)

    with patch(f"{_MODULE}.aget_s3_client", return_value=_FakeS3ClientCM(s3_client)):
        await sink.clear()


@pytest.mark.asyncio
async def test_clear_still_sweeps_abandoned_siblings_when_own_prefix_delete_fails():
    # A permissions error (or any other non-FileNotFoundError) deleting the own prefix must not
    # skip the sibling-sweep backstop, which is an independent cleanup — otherwise abandoned sibling
    # prefixes from crashed jobs never get swept on every run where the own-prefix delete fails.
    sink = _sink()
    stale_file = f"{sink._get_binding_prefix()}/job-old/chunk_0.parquet"
    s3_client = _s3_client(
        find_result={stale_file: {"LastModified": datetime.now(UTC) - ABANDONED_STAGED_PREFIX_TTL - timedelta(days=1)}}
    )
    s3_client._rm = AsyncMock(side_effect=[PermissionError("Access Denied"), None])

    with patch(f"{_MODULE}.aget_s3_client", return_value=_FakeS3ClientCM(s3_client)):
        with pytest.raises(PermissionError):
            await sink.clear()

    removed = [call.args[0] for call in s3_client._rm.await_args_list]
    assert [f"s3://{stale_file}"] in removed  # sibling sweep still ran despite the own-prefix failure


@parameterized.expand([("schema", schema_binding("schema-1")), ("saved_query", saved_query_binding("view-1"))])
@pytest.mark.asyncio
async def test_stages_under_the_binding_it_was_built_for(_name, binding):
    # A view materialization and an import job build the same sink; the binding is what keeps their
    # staged rows apart, so a source only ever consumes rows from the object it reads.
    sink = _sink(binding=binding)
    with (
        patch(f"{_MODULE}.person_property_projection_for", return_value=[_projection("distinct_id", "plan")]) as gate,
        patch.object(sink, "_get_fs", return_value=MagicMock()),
        patch(f"{_MODULE}.asyncio.to_thread", new=AsyncMock()) as to_thread,
    ):
        await sink.stage_chunk(chunk=0, table=_table())

    gate.assert_called_once_with(1, binding)
    assert to_thread.await_args is not None
    assert to_thread.await_args.args[2].startswith(f"{sink._get_path_prefix()}/")
