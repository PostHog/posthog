from datetime import UTC, datetime, timedelta

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.conf import settings
from django.db import OperationalError

import pyarrow as pa
import pyarrow.parquet as pq

from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import (
    AccountPropertySourceProjection,
    saved_query_binding,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.account_property_paths import (
    completion_prefix,
    job_staged_prefix,
    snapshot_prefix,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.account_property_row_sink import (
    ABANDONED_STAGED_PREFIX_TTL,
    AccountPropertyRowSink,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.account_property_row_sink"


def _sink() -> AccountPropertyRowSink:
    logger = MagicMock()
    logger.adebug = AsyncMock()
    return AccountPropertyRowSink(
        team_id=7,
        binding=saved_query_binding("019f0000-0000-7000-8000-000000000001"),
        job_id="job-1",
        logger=logger,
    )


def test_all_account_property_artifacts_use_the_data_modeling_prefix() -> None:
    binding = saved_query_binding("019f0000-0000-7000-8000-000000000001")

    paths = [
        job_staged_prefix(7, binding, "job-1"),
        snapshot_prefix(7, binding, "source-1", "tracked"),
        completion_prefix(7, binding, "job-1"),
    ]

    expected_root = settings.BUCKET_URL.removeprefix("s3://").rstrip("/")
    assert all(path.startswith(f"{expected_root}/") for path in paths)


class _S3ClientContext:
    def __init__(self, client: MagicMock) -> None:
        self.client = client

    async def __aenter__(self) -> MagicMock:
        return self.client

    async def __aexit__(self, *args) -> bool:
        return False


@pytest.mark.asyncio
async def test_stages_only_columns_from_sources_with_a_present_key() -> None:
    sink = _sink()
    projection = [
        AccountPropertySourceProjection(
            key_column="organization_id",
            columns=frozenset({"organization_id", "mrr"}),
        ),
        AccountPropertySourceProjection(
            key_column="missing_id",
            columns=frozenset({"missing_id", "plan"}),
        ),
    ]
    table = pa.table(
        {
            "organization_id": ["org-1"],
            "mrr": [100],
            "plan": ["pro"],
            "unused": ["x"],
        }
    )

    with (
        patch(f"{_MODULE}.account_property_projection_for", return_value=projection),
        patch.object(sink, "_get_fs", return_value=MagicMock()),
        patch(f"{_MODULE}.asyncio.to_thread", new=AsyncMock()) as to_thread,
    ):
        await sink.stage_chunk(0, table)

    assert to_thread.await_args is not None
    assert to_thread.await_args.args[1].column_names == ["mrr", "organization_id"]
    expected_root = settings.BUCKET_URL.removeprefix("s3://").rstrip("/")
    assert to_thread.await_args.args[2].startswith(f"{expected_root}/account_property_sync/7/model_")


@pytest.mark.asyncio
async def test_should_run_retries_once_on_a_transient_db_connection_drop() -> None:
    # A long-lived Temporal worker's pooled app-DB connection can go stale (pooler recycle,
    # failover, deploy) between syncs. Without a retry, that one-off OperationalError would
    # propagate and get treated as "no account-property mapping to sync" for the whole run
    # instead of the transient blip it is.
    sink = _sink()
    projection = [
        AccountPropertySourceProjection(key_column="organization_id", columns=frozenset({"organization_id", "mrr"}))
    ]
    resolver = MagicMock(side_effect=[OperationalError("server closed the connection unexpectedly"), projection])

    with patch(f"{_MODULE}.account_property_projection_for", resolver):
        assert await sink.should_run() is True

    assert resolver.call_count == 2


@pytest.mark.asyncio
async def test_stages_an_exact_delta_snapshot_after_materialization() -> None:
    sink = _sink()
    table = pa.table({"organization_id": ["org-1"], "mrr": [100]})
    output = pa.BufferOutputStream()
    pq.write_table(table, output)
    delta_table = MagicMock()
    delta_table.file_uris.return_value = ["s3://data-warehouse/dlt/file.parquet"]
    filesystem = MagicMock()
    filesystem.open_input_file.return_value = pa.BufferReader(output.getvalue())

    with (
        patch.object(
            sink,
            "_get_projection",
            new=AsyncMock(
                return_value=[
                    AccountPropertySourceProjection(
                        key_column="organization_id",
                        columns=frozenset({"organization_id", "mrr"}),
                    )
                ]
            ),
        ),
        patch.object(sink, "clear", new=AsyncMock()) as clear,
        patch.object(sink, "stage_chunk", new=AsyncMock()) as stage_chunk,
        patch.object(sink, "_get_fs", return_value=filesystem),
        patch(f"{_MODULE}.deltalake.DeltaTable", return_value=delta_table) as open_delta,
        patch(f"{_MODULE}.delta_storage_options", return_value={"region_name": "us-east-1"}),
    ):
        staged = await sink.stage_delta_snapshot("s3://data-warehouse/dlt/table", 7)

    assert staged is True
    clear.assert_awaited_once()
    open_delta.assert_called_once_with(
        "s3://data-warehouse/dlt/table",
        version=7,
        storage_options={"region_name": "us-east-1"},
    )
    stage_chunk.assert_awaited_once()
    assert stage_chunk.await_args is not None
    assert stage_chunk.await_args.args[1].to_pydict() == table.to_pydict()


@pytest.mark.asyncio
async def test_retry_clears_its_staged_files_and_sweeps_abandoned_jobs() -> None:
    sink = _sink()
    stale_file = f"{sink._get_binding_prefix()}/job-old/chunk.parquet"
    client = MagicMock()
    client._find = AsyncMock(
        return_value={stale_file: {"LastModified": datetime.now(UTC) - ABANDONED_STAGED_PREFIX_TTL - timedelta(days=1)}}
    )
    client._rm = AsyncMock()

    with patch(f"{_MODULE}.aget_s3_client", return_value=_S3ClientContext(client)):
        await sink.clear()

    removed = [call.args[0] for call in client._rm.await_args_list]
    assert f"s3://{sink._get_path_prefix()}/" in removed
    assert [f"s3://{stale_file}"] in removed
