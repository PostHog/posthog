import json
import uuid
import typing
import asyncio
import hashlib

from django.conf import settings
from django.db.utils import OperationalError as DjangoOperationalError

import orjson
import pyarrow as pa
import pyarrow.fs as pa_fs
import pyarrow.parquet as pq
from prometheus_client import Counter
from pyarrow.parquet import write_table
from structlog.types import FilteringBoundLogger

from posthog.hogql.database.database import get_data_warehouse_table_name

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.kafka_client.routing import KafkaClusterProfile, async_producer_scope
from posthog.kafka_client.topics import KAFKA_DWH_CDP_RAW_TABLE
from posthog.sync import database_sync_to_async_pool

from products.cdp.backend.models.hog_functions import HogFunction
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.data_warehouse.backend.facade.api import aget_s3_client, ensure_bucket_exists
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.pipelines.helpers import build_table_name
from products.warehouse_sources.backend.temporal.data_imports.util import PostHogInternalDatabaseError
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

# Per-file exceptions are swallowed (the file is deleted and the run continues), so a failed file
# is silently dropped rows. The outcome label is what makes that visible to alerting.
CDP_PRODUCER_FILES_TOTAL = Counter(
    "warehouse_cdp_producer_files_total",
    "Staged CDP files read from S3 and produced to Kafka, by outcome",
    labelnames=["team_id", "outcome"],
)

CDP_PRODUCER_ROWS_TOTAL = Counter(
    "warehouse_cdp_producer_rows_total",
    "Warehouse rows produced to the CDP raw-table Kafka topic",
    labelnames=["team_id"],
)

TableKind = typing.Literal["source", "view"]

# Trigger identifiers a HogFunction's `filters.source` or a HogFlow's `trigger.type` carries,
# keyed by the kind of warehouse table the rows came from.
TRIGGER_SOURCE_BY_KIND: dict[TableKind, str] = {
    "source": "data-warehouse-table",
    "view": "data-warehouse-view",
}


@frozen
class CDPTriggerTable:
    """The warehouse table a producer run emits rows for.

    A source-synced table is identified by its ExternalDataSchema, a materialized view by its
    DataWarehouseSavedQuery. The two share every step after this — the staging area, the Kafka
    topic, the consumer — so they differ only in how the table's name and subscribers resolve.
    """

    kind: TableKind
    id: str


class CDPProducer:
    team_id: int
    table: CDPTriggerTable
    job_id: str
    logger: FilteringBoundLogger
    _should_run_cache: bool | None
    _table_name_cache: str | None
    _fs_cache: pa_fs.S3FileSystem | None

    def __init__(self, team_id: int, table: CDPTriggerTable, job_id: str, logger: FilteringBoundLogger) -> None:
        self.team_id = team_id
        self.table = table
        self.job_id = job_id
        self.logger = logger
        self._should_run_cache = None
        self._table_name_cache = None
        self._fs_cache = None

    @classmethod
    def for_source(cls, *, team_id: int, schema_id: str, job_id: str, logger: FilteringBoundLogger) -> "CDPProducer":
        return cls(team_id, CDPTriggerTable(kind="source", id=schema_id), job_id, logger)

    @classmethod
    def for_view(cls, *, team_id: int, saved_query_id: str, job_id: str, logger: FilteringBoundLogger) -> "CDPProducer":
        return cls(team_id, CDPTriggerTable(kind="view", id=saved_query_id), job_id, logger)

    def _get_fs(self) -> pa_fs.S3FileSystem:
        # Cached per instance: stage_chunk() calls this once per chunk, and a producer lives for
        # a whole sync (potentially thousands of chunks). A fresh S3FileSystem per call opens its
        # own AWS SDK client/connections that outlive the call, exhausting the process' file
        # descriptor limit over a long sync.
        if self._fs_cache is not None:
            return self._fs_cache

        if settings.USE_LOCAL_SETUP:
            ensure_bucket_exists(
                f"s3://{self._get_path_prefix()}",
                settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY,
                settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET,
                settings.OBJECT_STORAGE_ENDPOINT,
            )

            self._fs_cache = pa_fs.S3FileSystem(
                access_key=settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY,
                secret_key=settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET,
                endpoint_override=settings.OBJECT_STORAGE_ENDPOINT,
            )
        else:
            self._fs_cache = pa_fs.S3FileSystem()

        return self._fs_cache

    def _get_path_prefix(self) -> str:
        # Views get their own middle segment so the two kinds never share a prefix and the source
        # layout stays exactly what it was.
        segment = self.table.id if self.table.kind == "source" else f"view_{self.table.id}"
        return f"{settings.DATAWAREHOUSE_BUCKET}/cdp_producer/{self.team_id}/{segment}/{self.job_id}"

    async def _list_files_to_produce(self) -> list[str]:
        async with aget_s3_client() as s3_client:
            try:
                ls_res = await s3_client._ls(f"s3://{self._get_path_prefix()}/", detail=True)
                ls_values = ls_res.values() if isinstance(ls_res, dict) else ls_res
                files = [f["Key"] for f in ls_values if f["type"] != "directory"]
                return files
            except FileNotFoundError:
                return []
            except PermissionError:
                # The worker may lack an s3:ListBucket grant on the cdp_producer/ prefix. Row
                # staging is best effort, so degrade to producing nothing and log a warning rather
                # than raise into error tracking.
                await self.logger.awarning(
                    f"No permission to list CDP staging files at {self._get_path_prefix()}; skipping CDP row staging"
                )
                return []

    def _serialize_json(self, record: object, *, sort_keys: bool = False) -> bytes:
        try:
            # `default=str` covers Decimal, which orjson refuses natively and which materialized
            # view aggregates produce routinely. Without it the fallback below stringifies every
            # value in the row, not just the offending one.
            return orjson.dumps(record, default=str, option=orjson.OPT_SORT_KEYS if sort_keys else None)
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
            if self.table.kind == "view":
                # A saved query's name is already the name it is queryable by in HogQL.
                return DataWarehouseSavedQuery.objects.values_list("name", flat=True).get(
                    id=self.table.id, team_id=self.team_id
                )

            schema = ExternalDataSchema.objects.get(id=self.table.id, team_id=self.team_id)
            raw_table_name = build_table_name(schema.source, schema.name)
            return get_data_warehouse_table_name(schema.source, raw_table_name)

        self._table_name_cache = await _resolve()
        return self._table_name_cache

    def _build_event_id(self, row: object) -> str:
        """Build a deterministic event id for a row.

        The row is hashed with sorted keys, so the id is stable for identical row data and changes
        whenever the data changes.

        A source sync also mixes in the job id: the same row arriving in a later sync is a new
        delivery. A materialized view does not, because its incremental filter is inclusive of the
        watermark — the rows on the boundary are recomputed and re-emitted on every run without
        having changed. Keying those on content alone lets a destination recognize the repeat.
        """
        row_hash = hashlib.sha256(self._serialize_json(row, sort_keys=True)).hexdigest()
        scope = self.table.id if self.table.kind == "view" else self.job_id
        return str(uuid.uuid5(uuid.NAMESPACE_OID, f"{scope}:{row_hash}"))

    def _view_can_trigger(self) -> bool:
        """Only a user-created, materialized saved query can drive a trigger.

        Endpoints carry a version suffix (`name_v1`), so a trigger's stored name would break on
        every version bump, and managed viewsets are generated by other products rather than chosen
        by the user.
        """
        return (
            DataWarehouseSavedQuery.objects.filter(
                id=self.table.id,
                team_id=self.team_id,
                is_materialized=True,
                is_test=False,
                origin=DataWarehouseSavedQuery.Origin.DATA_WAREHOUSE,
            )
            .exclude(deleted=True)
            .exists()
        )

    async def should_run(self) -> bool:
        if self._should_run_cache is not None:
            return self._should_run_cache

        dot_notated_table_name = await self.get_dot_notated_table_name()
        trigger_source = TRIGGER_SOURCE_BY_KIND[self.table.kind]

        @database_sync_to_async_pool
        def _check() -> bool:
            self.logger.debug(f"Checking if table {dot_notated_table_name} is used in any hog functions or workflows")
            self.logger.debug(f"Using table_name = {dot_notated_table_name}, source = {trigger_source}")

            try:
                if self.table.kind == "view" and not self._view_can_trigger():
                    return False

                has_matching_hog_function = (
                    HogFunction.objects.filter(
                        team_id=self.team_id,
                        enabled=True,
                        filters__source=trigger_source,
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
                    trigger__type=trigger_source,
                    trigger__table_name=dot_notated_table_name,
                ).exists()
            except (DjangoOperationalError, OSError) as e:
                # This queries PostHog's own database, not the source being synced. A transient
                # failure reaching it (e.g. a DNS blip resolving our host) stringifies with the
                # same wording a customer's misconfigured source host would, which the source's
                # `get_non_retryable_errors` would misclassify as non-retryable and permanently
                # stop a healthy sync. Re-raise clear of those substrings so it stays retryable.
                # A bare OSError (e.g. "Too many open files") reaches here unwrapped rather than as
                # a DjangoOperationalError when the worker runs out of file descriptors while
                # opening the connection's selector, before libpq has anything to report — same
                # transient condition, different exception type depending on which connect step it
                # hits, so both need the same reclassification.
                raise PostHogInternalDatabaseError(
                    "Failed to check hog function/workflow triggers in PostHog's database"
                ) from e

        self._should_run_cache = await _check()
        return self._should_run_cache

    async def clear(self):
        async with aget_s3_client() as s3_client:
            await self.logger.adebug(f"Clearing S3 chunks at path prefix {self._get_path_prefix()}")

            if len(await self._list_files_to_produce()) > 0:
                try:
                    await s3_client._rm(f"s3://{self._get_path_prefix()}/", recursive=True)
                except FileNotFoundError:
                    pass

    async def stage_chunk(self, chunk: int, table: pa.Table | pa.RecordBatch) -> None:
        await self.logger.adebug(f"Writing chunk {chunk} for CDP producer to S3 path prefix {self._get_path_prefix()}")

        # The import pipeline hands over tables, the data modeling activity record batches. Normalize
        # here so neither call site has to know what parquet writing wants. from_batches is zero-copy.
        if isinstance(table, pa.RecordBatch):
            table = pa.Table.from_batches([table])

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
        # destinations and workflows against their configured table without an extra lookup.
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
                                    "table_type": self.table.kind,
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
                    CDP_PRODUCER_FILES_TOTAL.labels(team_id=str(self.team_id), outcome="produced").inc()
                    await self.logger.adebug(f"Finished producing file {file_path} to Kafka")
                except Exception as e:
                    CDP_PRODUCER_FILES_TOTAL.labels(team_id=str(self.team_id), outcome="failed").inc()
                    capture_exception(e)
                    await self.logger.adebug(f"Error producing file {file_path} to Kafka: {e}")
                finally:
                    # TODO(Gilbert09): have better row tracking so we can retry from a particular row
                    if row_index:
                        CDP_PRODUCER_ROWS_TOTAL.labels(team_id=str(self.team_id)).inc(row_index)
                    await self.logger.adebug(f"Produced {row_index} rows")
                    await self.logger.adebug(f"Deleting file {file_path}")
                    await asyncio.to_thread(fs.delete_file, file_path)

            await self.logger.adebug("Finished producing all CDP data to Kafka")
