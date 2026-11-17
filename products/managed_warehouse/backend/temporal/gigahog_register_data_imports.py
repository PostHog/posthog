"""Write a prepared data import generation to Gigahog, PostHog's multi-tenant hoglake, over its REST API.

Each team's imports live in Gigahog namespace `team_<id>` of the imports catalog, under the name PostHog gives the
import in HogQL, and reach the customer later as `hoglake.team_<id>.<table>`. The files sit below
`<imports data path>org_id=<org>/team_id=<team>/<table>/`, the only place Gigahog accepts files for `team_<id>`.

One replacement commit ends every live file of the table and adds the generation's files in one snapshot, so readers
see the old rows or the new rows, never a mix.

This module must not import the workflow module: the workflow imports it.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pyarrow as pa
import structlog
import pyarrow.parquet as pq
from temporalio.exceptions import ApplicationError

from posthog.dataclasses import frozen

from products.managed_warehouse.backend.backfill_trino import hoglake_schema
from products.managed_warehouse.backend.temporal.ducklake_register_data_imports_trino import ParquetFilesystem
from products.managed_warehouse.backend.temporal.gigahog_client import (
    ORG_MARKED_CONTAINMENT_CAPABILITY,
    GigahogClient,
    GigahogColumn,
    GigahogConfig,
    GigahogError,
    GigahogFile,
    GigahogTable,
)
from products.managed_warehouse.backend.temporal.hoglake_register_data_imports import DROPPABLE_HIVE_PARTITION_COLUMNS

LOGGER = structlog.get_logger(__name__)

_FOOTER_READ_CONCURRENCY = 16
# One replacement commit must carry the whole generation to stay atomic, so a larger generation is refused instead of
# split. The bound matches the hoglake add_files limit that the interim hoglake path works under.
REPLACEMENT_MAX_FILES = 10_000
COMMIT_CONFLICT_ATTEMPTS = 3

_SCALAR_TYPES: dict[pa.DataType, str] = {
    pa.bool_(): "boolean",
    pa.int8(): "int8",
    pa.int16(): "int16",
    pa.int32(): "int",
    pa.int64(): "long",
    pa.float32(): "float",
    pa.float64(): "double",
    pa.string(): "string",
    pa.large_string(): "string",
    pa.string_view(): "string",
    pa.binary(): "binary",
    pa.large_binary(): "binary",
    pa.binary_view(): "binary",
    pa.date32(): "date",
    pa.time64("us"): "time",
}
# hoglake has no tz-aware type in another unit, so only a microsecond timestamp keeps its zone.
_NAIVE_TIMESTAMP_TYPES = {"s": "timestamp_s", "ms": "timestamp_ms", "us": "timestamp", "ns": "timestamp_ns"}
_MAX_DECIMAL_PRECISION = 38
_PARQUET_FIELD_ID = b"PARQUET:field_id"


@frozen
class GigahogRegistrationResult:
    published: bool
    row_count: int


@frozen
class _PreparedFile:
    path: str
    num_rows: int
    file_size_bytes: int
    footer_size: int
    schema: pa.Schema


def gigahog_config(
    *,
    url: str | None,
    catalog: str | None,
    data_path: str | None,
    token_url: str | None,
    client_id: str | None,
    client_secret: str | None,
    mark_namespaces: bool = False,
) -> GigahogConfig | None:
    """The writer's configuration, or None when the worker has no Gigahog to write to."""
    if not url:
        return None
    if not (catalog and data_path and token_url and client_id and client_secret):
        raise ApplicationError(
            "GIGAHOG_URL is set without every one of GIGAHOG_IMPORTS_CATALOG, GIGAHOG_IMPORTS_DATA_PATH, "
            "GIGAHOG_IMPORTS_TOKEN_URL, GIGAHOG_IMPORTS_CLIENT_ID and GIGAHOG_IMPORTS_CLIENT_SECRET",
            non_retryable=True,
        )
    if not data_path.startswith("s3://"):
        raise ApplicationError(f"GIGAHOG_IMPORTS_DATA_PATH '{data_path}' is not an s3:// prefix", non_retryable=True)
    return GigahogConfig(
        url=url,
        catalog=catalog,
        data_path=data_path.rstrip("/") + "/",
        token_url=token_url,
        client_id=client_id,
        client_secret=client_secret,
        mark_namespaces=mark_namespaces,
    )


def gigahog_team_prefix(data_path: str, *, organization_id: str, team_id: int) -> str:
    """The prefix that holds every import file of the team, with the canonical lower-case organization uuid."""
    return f"{data_path.rstrip('/')}/org_id={uuid.UUID(str(organization_id))}/team_id={int(team_id)}/"


def gigahog_landing_uri(
    data_path: str,
    *,
    organization_id: str,
    team_id: int,
    table_name: str,
    source_schema_id: str,
    job_id: str,
    generation_token: str,
) -> str:
    """`<team prefix><table>/<source schema>/<job>/<generation>`. The copy activity adds the attempt below it."""
    return (
        f"{gigahog_team_prefix(data_path, organization_id=organization_id, team_id=team_id)}"
        f"{table_name}/{source_schema_id}/{job_id}/{generation_token}"
    )


def gigahog_columns(schemas: Sequence[tuple[str, pa.Schema]]) -> tuple[GigahogColumn, ...]:
    """Union the file columns by name, in first-seen order.

    Every column is nullable, because a file may lack a column that another file has, and a reader takes it as NULL.
    Names that differ only in case are refused, because SQL engines that read the table fold them to one column.
    """
    columns: dict[str, GigahogColumn] = {}
    for path, schema in schemas:
        for arrow_field in schema:
            if arrow_field.metadata and _PARQUET_FIELD_ID in arrow_field.metadata:
                # Gigahog reads a file that carries field ids by id, and the writer's files carry the source's ids,
                # not the table's, so a column would silently read another column's values.
                raise ApplicationError(
                    f"Column '{arrow_field.name}' in {path} carries a Parquet field id, and the Gigahog import writer "
                    "registers only files whose columns Gigahog binds by name",
                    non_retryable=True,
                )
            type_name, type_params = _gigahog_type(arrow_field.type, column=arrow_field.name, path=path)
            column = GigahogColumn(name=arrow_field.name, type=type_name, type_params=type_params)
            existing = columns.get(arrow_field.name.lower())
            if existing is None:
                columns[arrow_field.name.lower()] = column
            elif existing.name != column.name:
                raise ApplicationError(
                    f"Columns '{existing.name}' and '{column.name}' differ only in case", non_retryable=True
                )
            elif existing != column:
                raise ApplicationError(
                    f"Column '{column.name}' is {existing.type} in one file and {column.type} in {path}",
                    non_retryable=True,
                )
    return tuple(columns.values())


def _gigahog_type(arrow_type: pa.DataType, *, column: str, path: str) -> tuple[str, dict[str, Any] | None]:
    scalar = _SCALAR_TYPES.get(arrow_type)
    if scalar is not None:
        return scalar, None
    if isinstance(arrow_type, pa.TimestampType):
        if arrow_type.tz is None:
            return _NAIVE_TIMESTAMP_TYPES[arrow_type.unit], None
        if arrow_type.unit == "us":
            return "timestamptz", None
    if isinstance(arrow_type, pa.Decimal128Type | pa.Decimal64Type | pa.Decimal32Type):
        if arrow_type.precision <= _MAX_DECIMAL_PRECISION:
            return "decimal", {"precision": arrow_type.precision, "scale": arrow_type.scale}
    raise ApplicationError(
        f"Column '{column}' in {path} has type {arrow_type}, which the Gigahog import writer does not map",
        non_retryable=True,
    )


def _columns_match(existing: Sequence[GigahogColumn], wanted: Sequence[GigahogColumn]) -> bool:
    def key(columns: Sequence[GigahogColumn]) -> dict[str, tuple[str, dict[str, Any]]]:
        return {column.name: (column.type, dict(column.type_params or {})) for column in columns}

    return key(existing) == key(wanted)


def _refuse_hive_partitions(hive_partition_columns: Sequence[str]) -> None:
    # The registered table is unpartitioned, and a value that exists only in a file path would be lost. The Delta
    # writer's bucket column holds no data of the source, so it may be left out.
    unsupported = [name for name in hive_partition_columns if name not in DROPPABLE_HIVE_PARTITION_COLUMNS]
    if unsupported:
        raise ApplicationError(
            f"Hive partition columns {unsupported} cannot be written to Gigahog, which reads values only from files",
            non_retryable=True,
        )


def _read_prepared_files(filesystem: ParquetFilesystem, paths: Sequence[str]) -> list[_PreparedFile]:
    def read(path: str) -> _PreparedFile:
        with filesystem.open(path, "rb") as file:
            file_size = file.seek(0, 2)
            file.seek(0)
            with pq.ParquetFile(file) as parquet_file:
                metadata = parquet_file.metadata
                return _PreparedFile(
                    path=path,
                    num_rows=metadata.num_rows,
                    file_size_bytes=file_size,
                    # The thrift FileMetaData length stored in the trailer, without the 8-byte length and magic.
                    footer_size=metadata.serialized_size,
                    schema=parquet_file.schema_arrow,
                )

    with ThreadPoolExecutor(max_workers=_FOOTER_READ_CONCURRENCY, thread_name_prefix="gigahog-footer") as executor:
        return list(executor.map(read, paths))


def _require_org_mark(client: GigahogClient, namespace: str, *, organization_id: str, team_id: int, mark: bool) -> None:
    """Refuse a namespace that is not marked as the team's, before any table goes in.

    Gigahog serves `team_<id>` to customers only when the namespace carries the org mark, and it refuses to mark a
    namespace that has ever held a table. A table created before the mark would therefore keep the team's imports
    from customers for good. With `mark`, the writer sets a missing mark itself; otherwise an operator or the
    provisioner sets it.
    """
    containment = client.namespace(namespace).containment
    expected_org = str(uuid.UUID(str(organization_id)))
    if containment is None and mark:
        if ORG_MARKED_CONTAINMENT_CAPABILITY not in client.capabilities():
            raise ApplicationError(
                f"The Gigahog catalog does not list {ORG_MARKED_CONTAINMENT_CAPABILITY}, so namespace {namespace} "
                "cannot carry the org mark yet",
                non_retryable=False,
            )
        client.mark_namespace(namespace, team_id=team_id, org=expected_org)
        LOGGER.info("Marked the team's Gigahog namespace with its org", namespace=namespace)
        containment = client.namespace(namespace).containment
    if containment is None or containment.org is None:
        raise ApplicationError(
            f"Gigahog namespace {namespace} has no org mark yet. Mark it as team {team_id} of organization "
            f"{expected_org} before the first import.",
            non_retryable=False,
        )
    if (containment.field, containment.value, containment.org) != ("team_id", int(team_id), expected_org):
        raise ApplicationError(
            f"Gigahog namespace {namespace} is marked {containment.field}={containment.value} of organization "
            f"{containment.org}, not team {team_id} of organization {expected_org}",
            non_retryable=True,
        )


def _table_for_commit(
    client: GigahogClient, namespace: str, table_name: str, columns: Sequence[GigahogColumn]
) -> GigahogTable:
    table = client.table(namespace, table_name)
    if table is None:
        table = client.create_table(namespace, table_name, columns)
        LOGGER.info("Created the Gigahog import table", table=f"{namespace}.{table_name}")
    elif not _columns_match(table.columns, columns):
        raise ApplicationError(
            f"The columns of Gigahog table {namespace}.{table_name} differ from the generation's, and the "
            "Gigahog import writer does not change a table's columns",
            non_retryable=True,
        )
    return table


def register_prepared_files_in_gigahog(
    *,
    config: GigahogConfig,
    organization_id: str,
    team_id: int,
    table_name: str,
    attempt_token: str,
    landing_uri: str,
    landing_paths: Sequence[str],
    hive_partition_columns: Sequence[str],
    filesystem: ParquetFilesystem,
    should_publish: Callable[[], bool],
    before_commit: Callable[[], None] | None = None,
    client: GigahogClient | None = None,
) -> GigahogRegistrationResult:
    """Replace Gigahog table `team_<id>.<table_name>` with the files under `landing_uri`.

    `attempt_token` is the registration's id, minted by the workflow and kept in its history. The commit's
    idempotency key comes from it and from the snapshot the commit is based on, so a commit repeated after a lost
    response adds nothing, and a commit based on a fresh read after a conflict has a key of its own.
    """
    namespace = hoglake_schema(team_id)
    team_prefix = gigahog_team_prefix(config.data_path, organization_id=organization_id, team_id=team_id)
    if not landing_uri.startswith(f"{team_prefix}{table_name}/"):
        raise ApplicationError(
            f"Refusing to register {landing_uri}, which is not under {team_prefix}{table_name}/", non_retryable=True
        )
    if not landing_paths:
        raise ApplicationError(f"No prepared Parquet files under {landing_uri}", non_retryable=True)
    if len(landing_paths) > REPLACEMENT_MAX_FILES:
        raise ApplicationError(
            f"The generation has {len(landing_paths)} files, and one Gigahog replacement carries at most "
            f"{REPLACEMENT_MAX_FILES}",
            non_retryable=True,
        )
    _refuse_hive_partitions(hive_partition_columns)

    prepared = _read_prepared_files(filesystem, sorted(landing_paths))
    columns = gigahog_columns([(file.path, file.schema) for file in prepared])
    row_count = sum(file.num_rows for file in prepared)

    owned_client = client is None
    gigahog = client or GigahogClient(config)
    try:
        if gigahog.create_namespace(namespace):
            LOGGER.info("Created the team's Gigahog namespace", namespace=namespace, catalog=config.catalog)
        _require_org_mark(
            gigahog, namespace, organization_id=organization_id, team_id=team_id, mark=config.mark_namespaces
        )
        if not should_publish():
            return GigahogRegistrationResult(published=False, row_count=0)
        files = [
            GigahogFile(
                path=file.path,
                record_count=file.num_rows,
                file_size_bytes=file.file_size_bytes,
                footer_size=file.footer_size,
            )
            for file in prepared
        ]
        for attempt in range(1, COMMIT_CONFLICT_ATTEMPTS + 1):
            table = _table_for_commit(gigahog, namespace, table_name, columns)
            if before_commit is not None:
                before_commit()
            try:
                commit = gigahog.replace_table_files(
                    table,
                    files,
                    idempotency_key=uuid.uuid5(uuid.UUID(attempt_token), str(table.read_snapshot_id)),
                    message=f"data import {attempt_token}",
                )
                break
            except GigahogError as error:
                # The table changed after the read, so the commit is based on a fresh read, under a new key.
                if error.code != "commit_conflict" or attempt == COMMIT_CONFLICT_ATTEMPTS:
                    raise
                LOGGER.warning("Gigahog refused a stale replacement, so the table is read again", table=table_name)
    except GigahogError as error:
        raise ApplicationError(str(error), non_retryable=not error.retryable) from error
    finally:
        if owned_client:
            gigahog.close()

    LOGGER.info(
        "Replaced the Gigahog import table",
        table=f"{namespace}.{table_name}",
        snapshot_id=commit.snapshot_id,
        ended_files=commit.ended_files,
        added_files=len(prepared),
        row_count=row_count,
    )
    return GigahogRegistrationResult(published=True, row_count=row_count)
