import json
import uuid
from contextlib import asynccontextmanager
from decimal import Decimal
from io import BytesIO

import pytest
from unittest import mock
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.db.utils import OperationalError as DjangoOperationalError

import pyarrow as pa
import pyarrow.parquet as pq
from asgiref.sync import sync_to_async
from parameterized import parameterized

from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.cdp_producer import CDPProducer
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source import PostgresSource
from products.warehouse_sources.backend.temporal.data_imports.util import PostHogInternalDatabaseError
from products.warehouse_sources.backend.types import ExternalDataSourceType
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow


def _patch_async_producer_scope(mock_producer):
    """Stub async_producer_scope so the context manager yields a mock producer."""

    @asynccontextmanager
    async def _scope(**_kwargs):
        yield mock_producer

    return patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.cdp_producer.async_producer_scope",
        _scope,
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_should_run_no_hog_function(team):
    source = await sync_to_async(ExternalDataSource.objects.create)(
        team=team, source_type=ExternalDataSourceType.POSTGRES
    )
    table = await sync_to_async(DataWarehouseTable.objects.create)(
        team=team, name="postgres_table_1", external_data_source=source
    )
    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        team=team, name="table_1", source=source, table=table
    )

    producer = CDPProducer.for_source(team_id=team.id, schema_id=str(schema.id), job_id="", logger=mock.AsyncMock())
    assert await producer.should_run() is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_should_run_with_matching_hog_function(team):
    source = await sync_to_async(ExternalDataSource.objects.create)(
        team=team, source_type=ExternalDataSourceType.POSTGRES
    )
    table = await sync_to_async(DataWarehouseTable.objects.create)(
        team=team, name="postgres_table_1", external_data_source=source
    )
    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        team=team, name="table_1", source=source, table=table
    )

    await sync_to_async(HogFunction.objects.create)(
        team=team,
        enabled=True,
        filters={"source": "data-warehouse-table", "data_warehouse": [{"table_name": "postgres.table_1"}]},
    )

    producer = CDPProducer.for_source(team_id=team.id, schema_id=str(schema.id), job_id="", logger=mock.AsyncMock())
    assert await producer.should_run() is True


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_should_not_produce_table_with_disabled_matching_hog_function(team):
    source = await sync_to_async(ExternalDataSource.objects.create)(
        team=team, source_type=ExternalDataSourceType.POSTGRES
    )
    table = await sync_to_async(DataWarehouseTable.objects.create)(
        team=team, name="postgres_table_1", external_data_source=source
    )
    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        team=team, name="table_1", source=source, table=table
    )

    await sync_to_async(HogFunction.objects.create)(
        team=team,
        enabled=False,
        filters={"source": "data-warehouse-table", "data_warehouse": [{"table_name": "postgres.table_1"}]},
    )

    producer = CDPProducer.for_source(team_id=team.id, schema_id=str(schema.id), job_id="", logger=mock.AsyncMock())
    assert await producer.should_run() is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_should_not_produce_table_with_deleted_matching_hog_function(team):
    source = await sync_to_async(ExternalDataSource.objects.create)(
        team=team, source_type=ExternalDataSourceType.POSTGRES
    )
    table = await sync_to_async(DataWarehouseTable.objects.create)(
        team=team, name="postgres_table_1", external_data_source=source
    )
    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        team=team, name="table_1", source=source, table=table
    )

    await sync_to_async(HogFunction.objects.create)(
        team=team,
        enabled=True,
        deleted=True,
        filters={"source": "data-warehouse-table", "data_warehouse": [{"table_name": "postgres.table_1"}]},
    )

    producer = CDPProducer.for_source(team_id=team.id, schema_id=str(schema.id), job_id="", logger=mock.AsyncMock())
    assert await producer.should_run() is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_should_run_with_new_style_table_name(team):
    source = await sync_to_async(ExternalDataSource.objects.create)(
        team=team, source_type=ExternalDataSourceType.POSTGRES
    )
    table = await sync_to_async(DataWarehouseTable.objects.create)(
        team=team, name="postgres.table_1", external_data_source=source
    )
    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        team=team, name="table_1", source=source, table=table
    )

    await sync_to_async(HogFunction.objects.create)(
        team=team,
        enabled=True,
        filters={"source": "data-warehouse-table", "data_warehouse": [{"table_name": "postgres.table_1"}]},
    )

    producer = CDPProducer.for_source(team_id=team.id, schema_id=str(schema.id), job_id="", logger=mock.AsyncMock())
    assert await producer.should_run() is True


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_should_run_with_source_prefix(team):
    source = await sync_to_async(ExternalDataSource.objects.create)(
        team=team, source_type=ExternalDataSourceType.POSTGRES, prefix="eu"
    )
    table = await sync_to_async(DataWarehouseTable.objects.create)(
        team=team, name="postgres_eu_table_1", external_data_source=source
    )
    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        team=team, name="table_1", source=source, table=table
    )

    await sync_to_async(HogFunction.objects.create)(
        team=team,
        enabled=True,
        filters={"source": "data-warehouse-table", "data_warehouse": [{"table_name": "postgres.eu.table_1"}]},
    )

    producer = CDPProducer.for_source(team_id=team.id, schema_id=str(schema.id), job_id="", logger=mock.AsyncMock())
    assert await producer.should_run() is True


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_should_run_with_leading_underscore_source_prefix(team):
    source = await sync_to_async(ExternalDataSource.objects.create)(
        team=team, source_type=ExternalDataSourceType.POSTGRES, prefix="_eu"
    )
    table = await sync_to_async(DataWarehouseTable.objects.create)(
        team=team, name="postgres_eu_table_1", external_data_source=source
    )
    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        team=team, name="table_1", source=source, table=table
    )

    await sync_to_async(HogFunction.objects.create)(
        team=team,
        enabled=True,
        filters={"source": "data-warehouse-table", "data_warehouse": [{"table_name": "postgres.eu.table_1"}]},
    )

    producer = CDPProducer.for_source(team_id=team.id, schema_id=str(schema.id), job_id="", logger=mock.AsyncMock())
    assert await producer.should_run() is True


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_should_run_with_matching_hog_flow(team):
    source = await sync_to_async(ExternalDataSource.objects.create)(
        team=team, source_type=ExternalDataSourceType.POSTGRES
    )
    table = await sync_to_async(DataWarehouseTable.objects.create)(
        team=team, name="postgres_table_1", external_data_source=source
    )
    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        team=team, name="table_1", source=source, table=table
    )

    await sync_to_async(HogFlow.objects.create)(
        team=team,
        status=HogFlow.State.ACTIVE,
        trigger={"type": "data-warehouse-table", "table_name": "postgres.table_1"},
    )

    producer = CDPProducer.for_source(team_id=team.id, schema_id=str(schema.id), job_id="", logger=mock.AsyncMock())
    assert await producer.should_run() is True


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_should_not_produce_table_with_draft_hog_flow(team):
    source = await sync_to_async(ExternalDataSource.objects.create)(
        team=team, source_type=ExternalDataSourceType.POSTGRES
    )
    table = await sync_to_async(DataWarehouseTable.objects.create)(
        team=team, name="postgres_table_1", external_data_source=source
    )
    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        team=team, name="table_1", source=source, table=table
    )

    await sync_to_async(HogFlow.objects.create)(
        team=team,
        status=HogFlow.State.DRAFT,
        trigger={"type": "data-warehouse-table", "table_name": "postgres.table_1"},
    )

    producer = CDPProducer.for_source(team_id=team.id, schema_id=str(schema.id), job_id="", logger=mock.AsyncMock())
    assert await producer.should_run() is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_should_not_produce_table_with_non_matching_hog_flow_table(team):
    source = await sync_to_async(ExternalDataSource.objects.create)(
        team=team, source_type=ExternalDataSourceType.POSTGRES
    )
    table = await sync_to_async(DataWarehouseTable.objects.create)(
        team=team, name="postgres_table_1", external_data_source=source
    )
    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        team=team, name="table_1", source=source, table=table
    )

    await sync_to_async(HogFlow.objects.create)(
        team=team,
        status=HogFlow.State.ACTIVE,
        trigger={"type": "data-warehouse-table", "table_name": "postgres.some_other_table"},
    )

    producer = CDPProducer.for_source(team_id=team.id, schema_id=str(schema.id), job_id="", logger=mock.AsyncMock())
    assert await producer.should_run() is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_should_run_with_both_hog_function_and_flow(team):
    source = await sync_to_async(ExternalDataSource.objects.create)(
        team=team, source_type=ExternalDataSourceType.POSTGRES
    )
    table = await sync_to_async(DataWarehouseTable.objects.create)(
        team=team, name="postgres_table_1", external_data_source=source
    )
    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        team=team, name="table_1", source=source, table=table
    )

    await sync_to_async(HogFunction.objects.create)(
        team=team,
        enabled=True,
        filters={"source": "data-warehouse-table", "data_warehouse": [{"table_name": "postgres.table_1"}]},
    )
    await sync_to_async(HogFlow.objects.create)(
        team=team,
        status=HogFlow.State.ACTIVE,
        trigger={"type": "data-warehouse-table", "table_name": "postgres.table_1"},
    )

    producer = CDPProducer.for_source(team_id=team.id, schema_id=str(schema.id), job_id="", logger=mock.AsyncMock())
    assert await producer.should_run() is True


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_cls,message",
    [
        (DjangoOperationalError, "[Errno -2] Name or service not known"),
        # Fd exhaustion opening the connection's selector surfaces as a bare OSError, unwrapped by
        # Django, rather than a DjangoOperationalError — same transient condition, different
        # exception type depending on which connect step runs out of file descriptors first.
        (OSError, "[Errno 24] Too many open files"),
    ],
)
async def test_should_run_posthog_database_connection_failure_stays_retryable(
    error_cls: type[Exception], message: str, team
):
    # `should_run` queries PostHog's own database (HogFunction/HogFlow), not the
    # source being synced. A transient connection failure there (e.g. a DNS blip resolving our
    # host) surfaces the same "Name or service not known" wording a customer's misconfigured
    # source host would, so it must be re-raised as PostHogInternalDatabaseError to avoid being
    # misclassified as non-retryable by the source's `get_non_retryable_errors`.
    source = await sync_to_async(ExternalDataSource.objects.create)(
        team=team, source_type=ExternalDataSourceType.POSTGRES
    )
    table = await sync_to_async(DataWarehouseTable.objects.create)(
        team=team, name="postgres_table_1", external_data_source=source
    )
    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        team=team, name="table_1", source=source, table=table
    )

    producer = CDPProducer.for_source(team_id=team.id, schema_id=str(schema.id), job_id="", logger=mock.AsyncMock())

    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.cdp_producer.HogFunction.objects"
    ) as mock_hog_function_objects:
        mock_hog_function_objects.filter.side_effect = error_cls(message)
        with pytest.raises(PostHogInternalDatabaseError) as exc_info:
            await producer.should_run()

    non_retryable = PostgresSource().get_non_retryable_errors()
    error_msg = str(exc_info.value)
    is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
    assert not is_non_retryable, f"A PostHog-side DB connection failure must stay retryable: {error_msg}"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.core.cdp_producer.aget_s3_client")
async def test_produce_to_kafka_from_s3_includes_table_name(mock_get_s3_client, team):
    source = await sync_to_async(ExternalDataSource.objects.create)(
        team=team, source_type=ExternalDataSourceType.POSTGRES
    )
    table = await sync_to_async(DataWarehouseTable.objects.create)(
        team=team, name="postgres_table_1", external_data_source=source
    )
    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        team=team, name="table_1", source=source, table=table
    )

    mock_s3_client = mock.AsyncMock()
    mock_s3_client._ls.return_value = [{"Key": "path/chunk_0.parquet", "type": "file"}]
    mock_get_s3_client.return_value.__aenter__ = mock.AsyncMock(return_value=mock_s3_client)
    mock_get_s3_client.return_value.__aexit__ = mock.AsyncMock(return_value=False)

    mock_kafka_producer = MagicMock()
    mock_kafka_producer.produce = mock.AsyncMock()
    mock_kafka_producer.flush = mock.AsyncMock()
    mock_kafka_producer.close = mock.AsyncMock()

    test_data = pa.table({"id": [1], "name": ["Alice"]})
    parquet_buffer = BytesIO()
    pq.write_table(test_data, parquet_buffer, compression="zstd")
    parquet_buffer.seek(0)

    mock_fs = MagicMock()
    mock_file = MagicMock()
    mock_file.__enter__ = MagicMock(return_value=parquet_buffer)
    mock_file.__exit__ = MagicMock(return_value=False)
    mock_fs.open_input_file.return_value = mock_file
    mock_fs.delete_file = MagicMock()

    producer = CDPProducer.for_source(
        team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=mock.AsyncMock()
    )

    with (
        patch.object(producer, "_get_fs", return_value=mock_fs),
        _patch_async_producer_scope(mock_kafka_producer),
    ):
        await producer.produce_to_kafka_from_s3()

    first_call_kwargs = mock_kafka_producer.produce.call_args_list[0][1]
    assert first_call_kwargs["data"]["team_id"] == team.id
    assert first_call_kwargs["data"]["table_name"] == "postgres.table_1"
    assert "id" in first_call_kwargs["data"]["properties"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.core.cdp_producer.aget_s3_client")
async def test_produce_to_kafka_from_s3_success(mock_get_s3_client, team):
    source = await sync_to_async(ExternalDataSource.objects.create)(
        team=team, source_type=ExternalDataSourceType.POSTGRES
    )
    table = await sync_to_async(DataWarehouseTable.objects.create)(
        team=team, name="postgres_table_1", external_data_source=source
    )
    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        team=team, name="table_1", source=source, table=table
    )

    mock_s3_client = mock.AsyncMock()
    mock_s3_client._ls.return_value = [
        {"Key": "path/chunk_0.parquet", "type": "file"},
        {"Key": "path/chunk_1.parquet", "type": "file"},
    ]
    mock_get_s3_client.return_value.__aenter__ = mock.AsyncMock(return_value=mock_s3_client)
    mock_get_s3_client.return_value.__aexit__ = mock.AsyncMock(return_value=False)

    mock_kafka_producer = MagicMock()
    mock_kafka_producer.produce = mock.AsyncMock()
    mock_kafka_producer.flush = mock.AsyncMock()
    mock_kafka_producer.close = mock.AsyncMock()

    test_data = pa.table({"id": [1, 2, 3], "name": ["Alice", "Bob", "Charlie"]})
    parquet_buffer = BytesIO()
    pq.write_table(test_data, parquet_buffer, compression="zstd")
    parquet_buffer.seek(0)

    mock_fs = MagicMock()
    mock_file = MagicMock()
    mock_file.__enter__ = MagicMock(return_value=parquet_buffer)
    mock_file.__exit__ = MagicMock(return_value=False)
    mock_fs.open_input_file.return_value = mock_file
    mock_fs.delete_file = MagicMock()

    producer = CDPProducer.for_source(
        team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=mock.AsyncMock()
    )

    with (
        patch.object(producer, "_get_fs", return_value=mock_fs),
        _patch_async_producer_scope(mock_kafka_producer),
    ):
        await producer.produce_to_kafka_from_s3()

    assert mock_kafka_producer.produce.call_count == 6
    assert mock_kafka_producer.flush.call_count == 2
    assert mock_fs.delete_file.call_count == 2

    first_call_kwargs = mock_kafka_producer.produce.call_args_list[0][1]
    assert first_call_kwargs["data"]["team_id"] == team.id
    assert "properties" in first_call_kwargs["data"]
    assert "id" in first_call_kwargs["data"]["properties"]

    # Each row carries a deterministic event id (valid UUID, stable per distinct row).
    # Both chunks contain the same 3 rows, so we expect 3 unique ids repeated across the 6 messages.
    event_ids = [call[1]["data"]["event_id"] for call in mock_kafka_producer.produce.call_args_list]
    assert all(uuid.UUID(event_id) for event_id in event_ids)
    assert len(set(event_ids)) == 3
    assert event_ids[:3] == event_ids[3:]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.core.cdp_producer.aget_s3_client")
async def test_produce_to_kafka_from_s3_with_no_files(mock_get_s3_client, team):
    source = await sync_to_async(ExternalDataSource.objects.create)(
        team=team, source_type=ExternalDataSourceType.POSTGRES
    )
    table = await sync_to_async(DataWarehouseTable.objects.create)(
        team=team, name="postgres_table_1", external_data_source=source
    )
    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        team=team, name="table_1", source=source, table=table
    )

    mock_s3_client = mock.AsyncMock()
    mock_s3_client._ls.side_effect = FileNotFoundError()
    mock_get_s3_client.return_value.__aenter__ = mock.AsyncMock(return_value=mock_s3_client)
    mock_get_s3_client.return_value.__aexit__ = mock.AsyncMock(return_value=False)

    mock_kafka_producer = MagicMock()
    mock_kafka_producer.produce = mock.AsyncMock()
    mock_kafka_producer.flush = mock.AsyncMock()
    mock_kafka_producer.close = mock.AsyncMock()

    mock_fs = MagicMock()
    producer = CDPProducer.for_source(
        team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=mock.AsyncMock()
    )

    with (
        patch.object(producer, "_get_fs", return_value=mock_fs),
        _patch_async_producer_scope(mock_kafka_producer),
    ):
        await producer.produce_to_kafka_from_s3()

    mock_kafka_producer.produce.assert_not_called()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.core.cdp_producer.aget_s3_client")
@patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.core.cdp_producer.capture_exception")
async def test_produce_to_kafka_from_s3_kafka_failure(mock_capture_exception, mock_get_s3_client, team):
    source = await sync_to_async(ExternalDataSource.objects.create)(
        team=team, source_type=ExternalDataSourceType.POSTGRES
    )
    table = await sync_to_async(DataWarehouseTable.objects.create)(
        team=team, name="postgres_table_1", external_data_source=source
    )
    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        team=team, name="table_1", source=source, table=table
    )

    mock_s3_client = mock.AsyncMock()
    mock_s3_client._ls.return_value = [{"Key": "path/chunk_0.parquet", "type": "file"}]
    mock_get_s3_client.return_value.__aenter__ = mock.AsyncMock(return_value=mock_s3_client)
    mock_get_s3_client.return_value.__aexit__ = mock.AsyncMock(return_value=False)

    mock_kafka_producer = MagicMock()
    mock_kafka_producer.produce = mock.AsyncMock(side_effect=Exception("Kafka connection failed"))
    mock_kafka_producer.flush = mock.AsyncMock()
    mock_kafka_producer.close = mock.AsyncMock()

    test_data = pa.table({"id": [1], "name": ["Alice"]})
    parquet_buffer = BytesIO()
    pq.write_table(test_data, parquet_buffer, compression="zstd")
    parquet_buffer.seek(0)

    mock_fs = MagicMock()
    mock_file = MagicMock()
    mock_file.__enter__ = MagicMock(return_value=parquet_buffer)
    mock_file.__exit__ = MagicMock(return_value=False)
    mock_fs.open_input_file.return_value = mock_file
    mock_fs.delete_file = MagicMock()

    producer = CDPProducer.for_source(
        team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=mock.AsyncMock()
    )

    with (
        patch.object(producer, "_get_fs", return_value=mock_fs),
        _patch_async_producer_scope(mock_kafka_producer),
    ):
        await producer.produce_to_kafka_from_s3()

    mock_capture_exception.assert_called_once()
    mock_fs.delete_file.assert_called_once()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.core.cdp_producer.aget_s3_client")
@patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.core.cdp_producer.capture_exception")
async def test_produce_to_kafka_from_s3_s3_read_failure(mock_capture_exception, mock_get_s3_client, team):
    source = await sync_to_async(ExternalDataSource.objects.create)(
        team=team, source_type=ExternalDataSourceType.POSTGRES
    )
    table = await sync_to_async(DataWarehouseTable.objects.create)(
        team=team, name="postgres_table_1", external_data_source=source
    )
    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        team=team, name="table_1", source=source, table=table
    )

    mock_s3_client = mock.AsyncMock()
    mock_s3_client._ls.return_value = [{"Key": "path/chunk_0.parquet", "type": "file"}]
    mock_get_s3_client.return_value.__aenter__ = mock.AsyncMock(return_value=mock_s3_client)
    mock_get_s3_client.return_value.__aexit__ = mock.AsyncMock(return_value=False)

    mock_kafka_producer = MagicMock()
    mock_kafka_producer.produce = mock.AsyncMock()
    mock_kafka_producer.flush = mock.AsyncMock()
    mock_kafka_producer.close = mock.AsyncMock()

    mock_fs = MagicMock()
    mock_fs.open_input_file.side_effect = Exception("S3 read failed")
    mock_fs.delete_file = MagicMock()

    producer = CDPProducer.for_source(
        team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=mock.AsyncMock()
    )

    with (
        patch.object(producer, "_get_fs", return_value=mock_fs),
        _patch_async_producer_scope(mock_kafka_producer),
    ):
        await producer.produce_to_kafka_from_s3()

    mock_capture_exception.assert_called_once()
    mock_kafka_producer.produce.assert_not_called()
    mock_fs.delete_file.assert_called_once()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.core.cdp_producer.aget_s3_client")
async def test_produce_to_kafka_from_s3_with_large_batch(mock_get_s3_client, team):
    source = await sync_to_async(ExternalDataSource.objects.create)(
        team=team, source_type=ExternalDataSourceType.POSTGRES
    )
    table = await sync_to_async(DataWarehouseTable.objects.create)(
        team=team, name="postgres_table_1", external_data_source=source
    )
    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        team=team, name="table_1", source=source, table=table
    )

    mock_s3_client = mock.AsyncMock()
    mock_s3_client._ls.return_value = [{"Key": "path/chunk_0.parquet", "type": "file"}]
    mock_get_s3_client.return_value.__aenter__ = mock.AsyncMock(return_value=mock_s3_client)
    mock_get_s3_client.return_value.__aexit__ = mock.AsyncMock(return_value=False)

    mock_kafka_producer = MagicMock()
    mock_kafka_producer.produce = mock.AsyncMock()
    mock_kafka_producer.flush = mock.AsyncMock()
    mock_kafka_producer.close = mock.AsyncMock()

    test_data = pa.table({"id": list(range(15000)), "value": [f"val_{i}" for i in range(15000)]})
    parquet_buffer = BytesIO()
    pq.write_table(test_data, parquet_buffer, compression="zstd")
    parquet_buffer.seek(0)

    mock_fs = MagicMock()
    mock_file = MagicMock()
    mock_file.__enter__ = MagicMock(return_value=parquet_buffer)
    mock_file.__exit__ = MagicMock(return_value=False)
    mock_fs.open_input_file.return_value = mock_file
    mock_fs.delete_file = MagicMock()

    producer = CDPProducer.for_source(
        team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=mock.AsyncMock()
    )

    with (
        patch.object(producer, "_get_fs", return_value=mock_fs),
        _patch_async_producer_scope(mock_kafka_producer),
    ):
        await producer.produce_to_kafka_from_s3()

    assert mock_kafka_producer.produce.call_count == 15000
    mock_kafka_producer.flush.assert_called_once()
    mock_fs.delete_file.assert_called_once()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stage_chunk(team):
    source = await sync_to_async(ExternalDataSource.objects.create)(
        team=team, source_type=ExternalDataSourceType.POSTGRES
    )
    table = await sync_to_async(DataWarehouseTable.objects.create)(
        team=team, name="postgres_table_1", external_data_source=source
    )
    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        team=team, name="table_1", source=source, table=table
    )

    mock_fs = MagicMock()
    test_data = pa.table({"id": [1, 2, 3], "name": ["Alice", "Bob", "Charlie"]})

    producer = CDPProducer.for_source(
        team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=mock.AsyncMock()
    )

    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.cdp_producer.write_table"
    ) as mock_write_table:
        with patch.object(producer, "_get_fs", return_value=mock_fs):
            await producer.stage_chunk(chunk=5, table=test_data)

    mock_write_table.assert_called_once()
    call_args = mock_write_table.call_args
    assert call_args[0][0] == test_data
    assert "chunk_5.parquet" in call_args[0][1]
    assert call_args[1]["filesystem"] == mock_fs
    assert call_args[1]["compression"] == "zstd"
    assert call_args[1]["use_dictionary"] is True


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stage_chunk_with_empty_table(team):
    source = await sync_to_async(ExternalDataSource.objects.create)(
        team=team, source_type=ExternalDataSourceType.POSTGRES
    )
    table = await sync_to_async(DataWarehouseTable.objects.create)(
        team=team, name="postgres_table_1", external_data_source=source
    )
    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        team=team, name="table_1", source=source, table=table
    )

    mock_fs = MagicMock()
    test_data = pa.table({"id": [], "name": []})

    producer = CDPProducer.for_source(
        team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=mock.AsyncMock()
    )

    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.cdp_producer.write_table"
    ) as mock_write_table:
        with patch.object(producer, "_get_fs", return_value=mock_fs):
            await producer.stage_chunk(chunk=0, table=test_data)

    mock_write_table.assert_called_once()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.core.cdp_producer.aget_s3_client")
async def test_clear_with_files(mock_get_s3_client, team):
    source = await sync_to_async(ExternalDataSource.objects.create)(
        team=team, source_type=ExternalDataSourceType.POSTGRES
    )
    table = await sync_to_async(DataWarehouseTable.objects.create)(
        team=team, name="postgres_table_1", external_data_source=source
    )
    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        team=team, name="table_1", source=source, table=table
    )

    mock_s3_client = mock.AsyncMock()
    mock_s3_client._ls.return_value = [
        {"Key": "path/chunk_0.parquet", "type": "file"},
        {"Key": "path/chunk_1.parquet", "type": "file"},
    ]
    mock_get_s3_client.return_value.__aenter__ = mock.AsyncMock(return_value=mock_s3_client)
    mock_get_s3_client.return_value.__aexit__ = mock.AsyncMock(return_value=False)

    producer = CDPProducer.for_source(
        team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=mock.AsyncMock()
    )

    await producer.clear()

    mock_s3_client._rm.assert_called_once()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.core.cdp_producer.aget_s3_client")
async def test_clear_with_no_files(mock_get_s3_client, team):
    source = await sync_to_async(ExternalDataSource.objects.create)(
        team=team, source_type=ExternalDataSourceType.POSTGRES
    )
    table = await sync_to_async(DataWarehouseTable.objects.create)(
        team=team, name="postgres_table_1", external_data_source=source
    )
    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        team=team, name="table_1", source=source, table=table
    )

    mock_s3_client = mock.AsyncMock()
    mock_s3_client._ls.side_effect = FileNotFoundError()
    mock_get_s3_client.return_value.__aenter__ = mock.AsyncMock(return_value=mock_s3_client)
    mock_get_s3_client.return_value.__aexit__ = mock.AsyncMock(return_value=False)

    producer = CDPProducer.for_source(
        team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=mock.AsyncMock()
    )

    await producer.clear()

    mock_s3_client._rm.assert_not_called()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.core.cdp_producer.aget_s3_client")
async def test_clear_handles_permission_error_on_list(mock_get_s3_client, team):
    source = await sync_to_async(ExternalDataSource.objects.create)(
        team=team, source_type=ExternalDataSourceType.POSTGRES
    )
    table = await sync_to_async(DataWarehouseTable.objects.create)(
        team=team, name="postgres_table_1", external_data_source=source
    )
    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        team=team, name="table_1", source=source, table=table
    )

    mock_s3_client = mock.AsyncMock()
    mock_s3_client._ls.side_effect = PermissionError("Access Denied")
    mock_get_s3_client.return_value.__aenter__ = mock.AsyncMock(return_value=mock_s3_client)
    mock_get_s3_client.return_value.__aexit__ = mock.AsyncMock(return_value=False)

    producer = CDPProducer.for_source(
        team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=mock.AsyncMock()
    )

    await producer.clear()

    mock_s3_client._rm.assert_not_called()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.core.cdp_producer.aget_s3_client")
async def test_clear_handles_file_not_found_on_delete(mock_get_s3_client, team):
    source = await sync_to_async(ExternalDataSource.objects.create)(
        team=team, source_type=ExternalDataSourceType.POSTGRES
    )
    table = await sync_to_async(DataWarehouseTable.objects.create)(
        team=team, name="postgres_table_1", external_data_source=source
    )
    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        team=team, name="table_1", source=source, table=table
    )

    mock_s3_client = mock.AsyncMock()
    mock_s3_client._ls.return_value = [{"Key": "path/chunk_0.parquet", "type": "file"}]
    mock_get_s3_client.return_value.__aenter__ = mock.AsyncMock(return_value=mock_s3_client)
    mock_get_s3_client.return_value.__aexit__ = mock.AsyncMock(return_value=False)

    mock_fs = MagicMock()
    mock_fs.delete_dir.side_effect = FileNotFoundError()

    producer = CDPProducer.for_source(
        team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=mock.AsyncMock()
    )

    with patch.object(producer, "_get_fs", return_value=mock_fs):
        await producer.clear()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_serialize_json_with_orjson_success(team):
    source = await sync_to_async(ExternalDataSource.objects.create)(
        team=team, source_type=ExternalDataSourceType.POSTGRES
    )
    table = await sync_to_async(DataWarehouseTable.objects.create)(
        team=team, name="postgres_table_1", external_data_source=source
    )
    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        team=team, name="table_1", source=source, table=table
    )

    producer = CDPProducer.for_source(
        team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=mock.AsyncMock()
    )

    record = {"id": 1, "name": "Alice", "score": 95.5}
    result = producer._serialize_json(record)

    assert isinstance(result, bytes)
    assert json.loads(result) == record


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_serialize_json_fallback_to_standard_json(team):
    source = await sync_to_async(ExternalDataSource.objects.create)(
        team=team, source_type=ExternalDataSourceType.POSTGRES
    )
    table = await sync_to_async(DataWarehouseTable.objects.create)(
        team=team, name="postgres_table_1", external_data_source=source
    )
    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        team=team, name="table_1", source=source, table=table
    )

    producer = CDPProducer.for_source(
        team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=mock.AsyncMock()
    )

    class CustomObject:
        def __str__(self):
            return "custom_value"

    record = {"id": 1, "custom": CustomObject()}

    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.cdp_producer.orjson.dumps"
    ) as mock_orjson:
        mock_orjson.side_effect = TypeError("Cannot serialize")
        result = producer._serialize_json(record)

    assert isinstance(result, bytes)
    deserialized = json.loads(result)
    assert deserialized["id"] == "1"
    assert deserialized["custom"] == "custom_value"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_serialize_json_fallback_with_stringify(team):
    source = await sync_to_async(ExternalDataSource.objects.create)(
        team=team, source_type=ExternalDataSourceType.POSTGRES
    )
    table = await sync_to_async(DataWarehouseTable.objects.create)(
        team=team, name="postgres_table_1", external_data_source=source
    )
    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        team=team, name="table_1", source=source, table=table
    )

    producer = CDPProducer.for_source(
        team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=mock.AsyncMock()
    )

    class UnserializableKey:
        def __str__(self):
            return "key_1"

    class UnserializableValue:
        def __str__(self):
            return "value_1"

    record = {UnserializableKey(): UnserializableValue()}

    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.cdp_producer.orjson.dumps"
    ) as mock_orjson:
        mock_orjson.side_effect = TypeError("Cannot serialize")
        result = producer._serialize_json(record)

    assert isinstance(result, bytes)
    deserialized = json.loads(result)
    assert deserialized["key_1"] == "value_1"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_serialize_json_raises_on_non_dict_unsupported(team):
    source = await sync_to_async(ExternalDataSource.objects.create)(
        team=team, source_type=ExternalDataSourceType.POSTGRES
    )
    table = await sync_to_async(DataWarehouseTable.objects.create)(
        team=team, name="postgres_table_1", external_data_source=source
    )
    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        team=team, name="table_1", source=source, table=table
    )

    producer = CDPProducer.for_source(
        team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=mock.AsyncMock()
    )

    class CompletelyUnserializable:
        pass

    record = CompletelyUnserializable()

    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.cdp_producer.orjson.dumps"
    ) as mock_orjson:
        mock_orjson.side_effect = TypeError("Cannot serialize")
        with pytest.raises(ValueError, match="Could not serialize record to JSON"):
            producer._serialize_json(record)


def _make_producer(job_id: str) -> CDPProducer:
    return CDPProducer.for_source(team_id=1, schema_id="schema_1", job_id=job_id, logger=mock.AsyncMock())


def _make_view_producer(job_id: str) -> CDPProducer:
    return CDPProducer.for_view(team_id=1, saved_query_id="view_1", job_id=job_id, logger=mock.AsyncMock())


@parameterized.expand([("local_setup", True), ("non_local_setup", False)])
def test_get_fs_reuses_the_same_filesystem_across_calls(_name, use_local_setup):
    # stage_chunk() calls _get_fs() once per chunk over a whole sync (potentially thousands of
    # chunks); constructing a fresh S3FileSystem per call leaks its underlying connections/file
    # descriptors until the process runs out of them. Both branches build their own S3FileSystem,
    # so both must cache it.
    producer = _make_producer("job_1")

    with (
        patch.object(settings, "USE_LOCAL_SETUP", use_local_setup),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.cdp_producer.pa_fs.S3FileSystem"
        ) as mock_s3_filesystem,
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.core.cdp_producer.ensure_bucket_exists"
        ),
    ):
        first = producer._get_fs()
        second = producer._get_fs()

    mock_s3_filesystem.assert_called_once()
    assert first is second


def test_build_event_id_is_a_valid_uuid():
    event_id = _make_producer("job_1")._build_event_id({"id": 1, "name": "Alice"})
    assert str(uuid.UUID(event_id)) == event_id


def test_build_event_id_is_stable_for_same_row_and_job():
    producer = _make_producer("job_1")
    row = {"id": 1, "name": "Alice"}
    assert producer._build_event_id(row) == producer._build_event_id(dict(row))


def test_build_event_id_is_independent_of_key_order():
    producer = _make_producer("job_1")
    assert producer._build_event_id({"id": 1, "name": "Alice"}) == producer._build_event_id({"name": "Alice", "id": 1})


@pytest.mark.parametrize(
    "row_a,row_b",
    [
        ({"id": 1, "name": "Alice"}, {"id": 1, "name": "Bob"}),
        ({"id": 1, "name": "Alice"}, {"id": 2, "name": "Alice"}),
        ({"id": 1}, {"id": 1, "name": "Alice"}),
        ({"value": 1}, {"value": "1"}),
    ],
)
def test_build_event_id_changes_when_row_data_changes(row_a, row_b):
    producer = _make_producer("job_1")
    assert producer._build_event_id(row_a) != producer._build_event_id(row_b)


def test_build_event_id_changes_with_job_id():
    row = {"id": 1, "name": "Alice"}
    assert _make_producer("job_1")._build_event_id(row) != _make_producer("job_2")._build_event_id(row)


def test_build_event_id_for_a_view_is_the_same_across_runs():
    # A view's incremental filter is inclusive of the watermark, so the boundary rows come back
    # unchanged on every run. Keying those on content alone is what lets a destination tell a
    # repeat from a genuine change.
    row = {"id": 1, "name": "Alice"}
    assert _make_view_producer("job_1")._build_event_id(row) == _make_view_producer("job_2")._build_event_id(row)


def test_build_event_id_for_a_view_still_changes_with_the_row():
    producer = _make_view_producer("job_1")
    assert producer._build_event_id({"id": 1}) != producer._build_event_id({"id": 2})


def test_serialize_json_keeps_other_fields_when_a_value_is_a_decimal():
    # Materialized view aggregates produce Decimals, which orjson refuses natively. The fallback
    # path stringifies every value in the row, so only the Decimal itself may degrade.
    serialized = _make_view_producer("job_1")._serialize_json({"id": 1, "amount": Decimal("10.50")})
    assert json.loads(serialized) == {"id": 1, "amount": "10.50"}


async def _create_view(team, **overrides) -> DataWarehouseSavedQuery:
    fields = {
        "team": team,
        "name": "daily_revenue",
        "query": {"kind": "HogQLQuery", "query": "select 1"},
        "is_materialized": True,
        "origin": DataWarehouseSavedQuery.Origin.DATA_WAREHOUSE,
        **overrides,
    }
    return await sync_to_async(DataWarehouseSavedQuery.objects.create)(**fields)


def _view_producer_for(view: DataWarehouseSavedQuery) -> CDPProducer:
    return CDPProducer.for_view(
        team_id=view.team_id, saved_query_id=str(view.id), job_id="test_job", logger=mock.AsyncMock()
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_view_should_run_with_matching_hog_function(team):
    view = await _create_view(team)
    await sync_to_async(HogFunction.objects.create)(
        team=team,
        enabled=True,
        filters={"source": "data-warehouse-view", "data_warehouse": [{"table_name": "daily_revenue"}]},
    )

    assert await _view_producer_for(view).should_run() is True


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_view_should_run_with_matching_hog_flow(team):
    view = await _create_view(team)
    await sync_to_async(HogFlow.objects.create)(
        team=team,
        name="test workflow",
        status=HogFlow.State.ACTIVE,
        trigger={"type": "data-warehouse-view", "table_name": "daily_revenue"},
        edges=[],
        actions=[],
    )

    assert await _view_producer_for(view).should_run() is True


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_view_does_not_match_a_source_table_subscriber_of_the_same_name(team):
    # A view's name and a source table's dot-notated name share one namespace, so the trigger type
    # is the only thing keeping the two apart.
    view = await _create_view(team)
    await sync_to_async(HogFunction.objects.create)(
        team=team,
        enabled=True,
        filters={"source": "data-warehouse-table", "data_warehouse": [{"table_name": "daily_revenue"}]},
    )

    assert await _view_producer_for(view).should_run() is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_source_table_does_not_match_a_view_subscriber_of_the_same_name(team):
    source = await sync_to_async(ExternalDataSource.objects.create)(
        team=team, source_type=ExternalDataSourceType.POSTGRES
    )
    table = await sync_to_async(DataWarehouseTable.objects.create)(
        team=team, name="postgres_table_1", external_data_source=source
    )
    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        team=team, name="table_1", source=source, table=table
    )
    await sync_to_async(HogFunction.objects.create)(
        team=team,
        enabled=True,
        filters={"source": "data-warehouse-view", "data_warehouse": [{"table_name": "postgres.table_1"}]},
    )

    producer = CDPProducer.for_source(team_id=team.id, schema_id=str(schema.id), job_id="", logger=mock.AsyncMock())
    assert await producer.should_run() is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"is_materialized": False},
        {"origin": DataWarehouseSavedQuery.Origin.ENDPOINT},
        {"origin": DataWarehouseSavedQuery.Origin.MANAGED_VIEWSET},
        {"is_test": True},
        {"deleted": True},
    ],
)
async def test_ineligible_views_never_produce(team, overrides):
    view = await _create_view(team, **overrides)
    await sync_to_async(HogFunction.objects.create)(
        team=team,
        enabled=True,
        filters={"source": "data-warehouse-view", "data_warehouse": [{"table_name": "daily_revenue"}]},
    )

    assert await _view_producer_for(view).should_run() is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_view_table_name_is_the_saved_query_name(team):
    view = await _create_view(team, name="my_view")
    assert await _view_producer_for(view).get_dot_notated_table_name() == "my_view"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.core.cdp_producer.aget_s3_client")
async def test_produce_to_kafka_from_s3_marks_view_rows(mock_get_s3_client, team):
    view = await _create_view(team, name="my_view")

    mock_s3_client = MagicMock()
    mock_s3_client._ls = mock.AsyncMock(return_value=[{"Key": "chunk_0.parquet", "type": "file"}])
    mock_get_s3_client.return_value.__aenter__ = mock.AsyncMock(return_value=mock_s3_client)
    mock_get_s3_client.return_value.__aexit__ = mock.AsyncMock(return_value=None)

    mock_kafka_producer = MagicMock()
    mock_kafka_producer.produce = mock.AsyncMock()
    mock_kafka_producer.flush = mock.AsyncMock()
    mock_kafka_producer.close = mock.AsyncMock()

    parquet_buffer = BytesIO()
    pq.write_table(pa.table({"id": [1]}), parquet_buffer, compression="zstd")
    parquet_buffer.seek(0)

    mock_fs = MagicMock()
    mock_file = MagicMock()
    mock_file.__enter__ = MagicMock(return_value=parquet_buffer)
    mock_file.__exit__ = MagicMock(return_value=False)
    mock_fs.open_input_file.return_value = mock_file
    mock_fs.delete_file = MagicMock()

    producer = _view_producer_for(view)

    with (
        patch.object(producer, "_get_fs", return_value=mock_fs),
        _patch_async_producer_scope(mock_kafka_producer),
    ):
        await producer.produce_to_kafka_from_s3()

    data = mock_kafka_producer.produce.call_args_list[0][1]["data"]
    assert data["table_name"] == "my_view"
    assert data["table_type"] == "view"


def test_staging_paths_never_collide_between_a_schema_and_a_view_of_the_same_id():
    shared_id = "11111111-1111-1111-1111-111111111111"
    source = CDPProducer.for_source(team_id=1, schema_id=shared_id, job_id="job", logger=mock.AsyncMock())
    view = CDPProducer.for_view(team_id=1, saved_query_id=shared_id, job_id="job", logger=mock.AsyncMock())

    assert source._get_path_prefix() != view._get_path_prefix()
