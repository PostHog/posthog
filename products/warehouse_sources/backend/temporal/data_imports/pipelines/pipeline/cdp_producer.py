import json
import uuid
import asyncio
import hashlib

from django.conf import settings
from django.db import OperationalError as DjangoOperationalError

import orjson
import pyarrow as pa
import pyarrow.fs as pa_fs
import pyarrow.parquet as pq
from pyarrow.parquet import write_table
from structlog.types import FilteringBoundLogger

from posthog.hogql.database.database import get_data_warehouse_table_name

from posthog.exceptions_capture import capture_exception
from posthog.kafka_client.routing import KafkaClusterProfile, async_producer_scope
from posthog.kafka_client.topics import KAFKA_DWH_CDP_RAW_TABLE
from posthog.sync import database_sync_to_async_pool

from products.cdp.backend.models.hog_functions import HogFunction
from products.data_warehouse.backend.facade.api import aget_s3_client, ensure_bucket_exists
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.pipelines.helpers import build_table_name
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow


class PostHogDatabaseConnectionError(Exception):
    """Raised when a CDP producer read from PostHog's own database fails to connect.

    `get_dot_notated_table_name` and `should_produce_table` read PostHog-side metadata
    (`ExternalDataSchema`, `HogFunction`, `HogFlow`), not the customer's source database. A
    transient failure reaching our database here (e.g. a DNS blip resolving our host) stringifies
    the same as a customer misconfiguration (e.g. "Name or service not known"), which the
    postgres/mysql/clickhouse sources all list in `get_non_retryable_errors`. Left unmapped it gets
    misclassified as a permanent customer config error and stops a healthy sync. This message
    intentionally avoids those connection-error substrings so it stays retryable.
    """


class CDPProducer:
    team_id: int
    schema_id: str
    job_id: str
    logger: FilteringBoundLogger
    _should_produce_cache: bool | None
    _table_name_cache: str | None

    def __init__(self, team_id: int, schema_id: str, job_id: str, logger: FilteringBoundLogger) -> None:
        self.team_id = team_id
        self.schema_id = schema_id
        self.job_id = job_id
        self.logger = logger
        self._should_produce_cache = None
        self._table_name_cache = None

    def _get_fs(self) -> pa_fs.S3FileSystem:
        if settings.USE_LOCAL_SETUP:
            ensure_bucket_exists(
                f"s3://{self._get_path_prefix()}",
                settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY,
                settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET,
                settings.OBJECT_STORAGE_ENDPOINT,
            )

            return pa_fs.S3FileSystem(
                access_key=settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY,
                secret_key=settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET,
                endpoint_override=settings.OBJECT_STORAGE_ENDPOINT,
            )

        return pa_fs.S3FileSystem()

    def _get_path_prefix(self) -> str:
        return f"{settings.DATAWAREHOUSE_BUCKET}/cdp_producer/{self.team_id}/{self.schema_id}/{self.job_id}"

    async def _list_files_to_produce(self) -> list[str]:
        async with aget_s3_client() as s3_client:
            try:
                ls_res = await s3_client._ls(f"s3://{self._get_path_prefix()}/", detail=True)
                ls_values = ls_res.values() if isinstance(ls_res, dict) else ls_res
                files = [f["Key"] for f in ls_values if f["type"] != "directory"]
                return files
            except FileNotFoundError:
                return []

    def _serialize_json(self, record: object, *, sort_keys: bool = False) -> bytes:
        try:
            return orjson.dumps(record, option=orjson.OPT_SORT_KEYS if sort_keys else None)
        except TypeError:
            try:
                return json.dumps(record, sort_keys=sort_keys).encode("utf-8")
            except Exception as e:
                if isinstance(record, dict):
                    record = {str(k): str(v) for k, v in record.items()}
                    return json.dumps(record, sort_keys=sort_keys).encode("utf-8")

                raise ValueError("Could not serialize record to JSON") from e

    async def get_dot_notated_table_name(self) -> str:
        if self._table_name_cache is not None:
            return self._table_name_cache

        @database_sync_to_async_pool
        def _resolve() -> str:
            try:
                schema = ExternalDataSchema.objects.get(id=self.schema_id, team_id=self.team_id)
            except DjangoOperationalError as e:
                raise PostHogDatabaseConnectionError("Failed to load sync metadata from PostHog's database") from e
            raw_table_name = build_table_name(schema.source, schema.name)
            return get_data_warehouse_table_name(schema.source, raw_table_name)

        self._table_name_cache = await _resolve()
        return self._table_name_cache

    def _build_event_id(self, row: object) -> str:
        """Build a deterministic event id that is unique per row per job.

        The row is hashed (sorted keys so re-runs of the same job produce the same hash)
        and combined with the job id, so the id is stable for the same row + job but
        changes whenever the row's data changes.
        """
        row_hash = hashlib.sha256(self._serialize_json(row, sort_keys=True)).hexdigest()
        return str(uuid.uuid5(uuid.NAMESPACE_OID, f"{self.job_id}:{row_hash}"))

    async def should_produce_table(self) -> bool:
        if self._should_produce_cache is not None:
            return self._should_produce_cache

        dot_notated_table_name = await self.get_dot_notated_table_name()

        @database_sync_to_async_pool
        def _check() -> bool:
            self.logger.debug(f"Checking if table {dot_notated_table_name} is used in any hog functions or workflows")
            self.logger.debug(f"Using table_name = {dot_notated_table_name}, source = data-warehouse-table")

            try:
                has_matching_hog_function = (
                    HogFunction.objects.filter(
                        team_id=self.team_id,
                        enabled=True,
                        filters__source="data-warehouse-table",
                        filters__data_warehouse__contains=[{"table_name": dot_notated_table_name}],
                    )
                    .exclude(deleted=True)
                    .exists()
                )

                if has_matching_hog_function:
                    return True

                # Also gate on active workflows (HogFlows) triggered by this table - without this the
                # producer never emits to Kafka for a team whose only consumer is a warehouse-triggered workflow.
                return HogFlow.objects.filter(
                    team_id=self.team_id,
                    status=HogFlow.State.ACTIVE,
                    trigger__type="data-warehouse-table",
                    trigger__table_name=dot_notated_table_name,
                ).exists()
            except DjangoOperationalError as e:
                raise PostHogDatabaseConnectionError("Failed to load sync metadata from PostHog's database") from e

        self._should_produce_cache = await _check()
        return self._should_produce_cache

    async def clear_s3_chunks(self):
        async with aget_s3_client() as s3_client:
            await self.logger.adebug(f"Clearing S3 chunks at path prefix {self._get_path_prefix()}")

            if len(await self._list_files_to_produce()) > 0:
                try:
                    await s3_client._rm(f"s3://{self._get_path_prefix()}/", recursive=True)
                except FileNotFoundError:
                    pass

    async def write_chunk_for_cdp_producer(self, chunk: int, table: pa.Table) -> None:
        await self.logger.adebug(f"Writing chunk {chunk} for CDP producer to S3 path prefix {self._get_path_prefix()}")

        # Write operations in pyarrow are CPU-bound, so run in thread pool
        await asyncio.to_thread(
            write_table,
            table,
            f"{self._get_path_prefix()}/chunk_{chunk}.parquet",
            filesystem=self._get_fs(),
            compression="zstd",
            use_dictionary=True,
        )

    async def produce_to_kafka_from_s3(self) -> None:
        fs = self._get_fs()

        await self.logger.adebug(f"Producing CDP data to Kafka from S3 path prefix {self._get_path_prefix()}")

        # Propagate the dot-notated table name so the Node consumer can match warehouse-triggered
        # workflows (HogFlows) against trigger.table_name without an extra lookup.
        dot_notated_table_name = await self.get_dot_notated_table_name()

        files_to_produce = await self._list_files_to_produce()

        await self.logger.adebug(f"Found {len(files_to_produce)} files to produce to Kafka")

        async with async_producer_scope(profile=KafkaClusterProfile.CYCLOTRON) as kafka_producer:
            for file_path in files_to_produce:
                await self.logger.adebug(f"Producing file {file_path} to Kafka")

                row_index = 0

                try:
                    with fs.open_input_file(file_path) as f:
                        pf = pq.ParquetFile(f)

                        for batch in pf.iter_batches(batch_size=10_000):
                            for row in batch.to_pylist():
                                row_as_props = {
                                    "team_id": self.team_id,
                                    "table_name": dot_notated_table_name,
                                    "event_id": self._build_event_id(row),
                                    "properties": row,
                                }
                                await kafka_producer.produce(
                                    topic=KAFKA_DWH_CDP_RAW_TABLE,
                                    data=row_as_props,
                                    value_serializer=self._serialize_json,
                                )
                                row_index += 1

                    await kafka_producer.flush()
                    await self.logger.adebug(f"Finished producing file {file_path} to Kafka")
                except Exception as e:
                    capture_exception(e)
                    await self.logger.adebug(f"Error producing file {file_path} to Kafka: {e}")
                finally:
                    # TODO(Gilbert09): have better row tracking so we can retry from a particular row
                    await self.logger.adebug(f"Produced {row_index} rows")
                    await self.logger.adebug(f"Deleting file {file_path}")
                    await asyncio.to_thread(fs.delete_file, file_path)

            await self.logger.adebug("Finished producing all CDP data to Kafka")
