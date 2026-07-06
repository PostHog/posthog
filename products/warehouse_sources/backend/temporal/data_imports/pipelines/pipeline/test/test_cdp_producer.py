import json
import uuid
from contextlib import asynccontextmanager
from io import BytesIO

import pytest
from unittest import mock
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pyarrow.parquet as pq
from asgiref.sync import sync_to_async

from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.cdp_producer import CDPProducer
from products.warehouse_sources.backend.types import ExternalDataSourceType
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow


def _patch_async_producer_scope(mock_producer):
    """Stub async_producer_scope so the context manager yields a mock producer."""

    @asynccontextmanager
    async def _scope(**_kwargs):
        yield mock_producer

    return patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.cdp_producer.async_producer_scope",
        _scope,
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_should_produce_table_no_hog_function(team):
    source = await sync_to_async(ExternalDataSource.objects.create)(
        team=team, source_type=ExternalDataSourceType.POSTGRES
    )
    table = await sync_to_async(DataWarehouseTable.objects.create)(
        team=team, name="postgres_table_1", external_data_source=source
    )
    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        team=team, name="table_1", source=source, table=table
    )

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="", logger=mock.AsyncMock())
    assert await producer.should_produce_table() is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_should_produce_table_with_matching_hog_function(team):
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

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="", logger=mock.AsyncMock())
    assert await producer.should_produce_table() is True


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

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="", logger=mock.AsyncMock())
    assert await producer.should_produce_table() is False


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

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="", logger=mock.AsyncMock())
    assert await producer.should_produce_table() is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_should_produce_table_with_new_style_table_name(team):
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

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="", logger=mock.AsyncMock())
    assert await producer.should_produce_table() is True


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_should_produce_table_with_source_prefix(team):
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

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="", logger=mock.AsyncMock())
    assert await producer.should_produce_table() is True


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_should_produce_table_with_leading_underscore_source_prefix(team):
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

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="", logger=mock.AsyncMock())
    assert await producer.should_produce_table() is True


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_should_produce_table_with_matching_hog_flow(team):
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

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="", logger=mock.AsyncMock())
    assert await producer.should_produce_table() is True


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

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="", logger=mock.AsyncMock())
    assert await producer.should_produce_table() is False


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

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="", logger=mock.AsyncMock())
    assert await producer.should_produce_table() is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_should_produce_table_with_both_hog_function_and_flow(team):
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

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="", logger=mock.AsyncMock())
    assert await producer.should_produce_table() is True


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.cdp_producer.aget_s3_client")
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

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=mock.AsyncMock())

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
@patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.cdp_producer.aget_s3_client")
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

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=mock.AsyncMock())

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
@patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.cdp_producer.aget_s3_client")
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
    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=mock.AsyncMock())

    with (
        patch.object(producer, "_get_fs", return_value=mock_fs),
        _patch_async_producer_scope(mock_kafka_producer),
    ):
        await producer.produce_to_kafka_from_s3()

    mock_kafka_producer.produce.assert_not_called()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.cdp_producer.aget_s3_client")
@patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.cdp_producer.capture_exception")
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

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=mock.AsyncMock())

    with (
        patch.object(producer, "_get_fs", return_value=mock_fs),
        _patch_async_producer_scope(mock_kafka_producer),
    ):
        await producer.produce_to_kafka_from_s3()

    mock_capture_exception.assert_called_once()
    mock_fs.delete_file.assert_called_once()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.cdp_producer.aget_s3_client")
@patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.cdp_producer.capture_exception")
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

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=mock.AsyncMock())

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
@patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.cdp_producer.aget_s3_client")
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

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=mock.AsyncMock())

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
async def test_write_chunk_for_cdp_producer(team):
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

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=mock.AsyncMock())

    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.cdp_producer.write_table"
    ) as mock_write_table:
        with patch.object(producer, "_get_fs", return_value=mock_fs):
            await producer.write_chunk_for_cdp_producer(chunk=5, table=test_data)

    mock_write_table.assert_called_once()
    call_args = mock_write_table.call_args
    assert call_args[0][0] == test_data
    assert "chunk_5.parquet" in call_args[0][1]
    assert call_args[1]["filesystem"] == mock_fs
    assert call_args[1]["compression"] == "zstd"
    assert call_args[1]["use_dictionary"] is True


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_write_chunk_for_cdp_producer_with_empty_table(team):
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

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=mock.AsyncMock())

    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.cdp_producer.write_table"
    ) as mock_write_table:
        with patch.object(producer, "_get_fs", return_value=mock_fs):
            await producer.write_chunk_for_cdp_producer(chunk=0, table=test_data)

    mock_write_table.assert_called_once()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.cdp_producer.aget_s3_client")
async def test_clear_s3_chunks_with_files(mock_get_s3_client, team):
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

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=mock.AsyncMock())

    await producer.clear_s3_chunks()

    mock_s3_client._rm.assert_called_once()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.cdp_producer.aget_s3_client")
async def test_clear_s3_chunks_with_no_files(mock_get_s3_client, team):
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

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=mock.AsyncMock())

    await producer.clear_s3_chunks()

    mock_s3_client._rm.assert_not_called()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@patch("products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.cdp_producer.aget_s3_client")
async def test_clear_s3_chunks_handles_file_not_found_on_delete(mock_get_s3_client, team):
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

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=mock.AsyncMock())

    with patch.object(producer, "_get_fs", return_value=mock_fs):
        await producer.clear_s3_chunks()


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

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=mock.AsyncMock())

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

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=mock.AsyncMock())

    class CustomObject:
        def __str__(self):
            return "custom_value"

    record = {"id": 1, "custom": CustomObject()}

    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.cdp_producer.orjson.dumps"
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

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=mock.AsyncMock())

    class UnserializableKey:
        def __str__(self):
            return "key_1"

    class UnserializableValue:
        def __str__(self):
            return "value_1"

    record = {UnserializableKey(): UnserializableValue()}

    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.cdp_producer.orjson.dumps"
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

    producer = CDPProducer(team_id=team.id, schema_id=str(schema.id), job_id="test_job", logger=mock.AsyncMock())

    class CompletelyUnserializable:
        pass

    record = CompletelyUnserializable()

    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.cdp_producer.orjson.dumps"
    ) as mock_orjson:
        mock_orjson.side_effect = TypeError("Cannot serialize")
        with pytest.raises(ValueError, match="Could not serialize record to JSON"):
            producer._serialize_json(record)


def _make_producer(job_id: str) -> CDPProducer:
    return CDPProducer(team_id=1, schema_id="schema_1", job_id=job_id, logger=mock.AsyncMock())


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
