from datetime import UTC, datetime, timedelta

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import pyarrow as pa

from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import (
    AccountPropertySourceProjection,
    saved_query_binding,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.account_property_row_sink import (
    ABANDONED_STAGED_PREFIX_TTL,
    AccountPropertyRowSink,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.account_property_row_sink"


def _sink(*, incremental: bool = False) -> AccountPropertyRowSink:
    logger = MagicMock()
    logger.adebug = AsyncMock()
    return AccountPropertyRowSink(
        team_id=7,
        binding=saved_query_binding("019f0000-0000-7000-8000-000000000001"),
        job_id="job-1",
        logger=logger,
        is_incremental=incremental,
    )


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
    assert "/account_property_sync/7/model_" in to_thread.await_args.args[2]


@pytest.mark.asyncio
async def test_incremental_retry_keeps_its_staged_files_and_sweeps_abandoned_jobs() -> None:
    sink = _sink(incremental=True)
    stale_file = f"{sink._get_binding_prefix()}/job-old/chunk.parquet"
    client = MagicMock()
    client._find = AsyncMock(
        return_value={stale_file: {"LastModified": datetime.now(UTC) - ABANDONED_STAGED_PREFIX_TTL - timedelta(days=1)}}
    )
    client._rm = AsyncMock()

    with patch(f"{_MODULE}.aget_s3_client", return_value=_S3ClientContext(client)):
        await sink.clear()

    removed = [call.args[0] for call in client._rm.await_args_list]
    assert f"s3://{sink._get_path_prefix()}/" not in removed
    assert [f"s3://{stale_file}"] in removed
