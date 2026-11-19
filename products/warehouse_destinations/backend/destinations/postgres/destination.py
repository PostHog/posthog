"""Write Arrow record batches into a Postgres table.

The namespace of a target is `(database, schema)`, and the database must be the one the
connection opens.

- APPEND copies rows straight into the final table.
- MERGE copies rows into a staging table. `commit` upserts the staging rows into the final table
  on the primary keys and drops the staging table in the same transaction.
- REPLACE copies rows into a staging table. `commit` swaps it into the final name in one
  transaction, so readers see the old table right up to the moment the new one is complete.

A staging table carries a batch-key column, so a retried write deletes the rows of its earlier
attempt first. A MERGE staging table also carries a row id, so `dedupe_source` keeps the last
written row of each key across all writes. The owner tag goes into the table comment, which
follows the table through the rename in a swap.
"""

import io
import csv
import json
import typing
import hashlib
import datetime as dt
import contextlib
import collections.abc

from django.conf import settings

import pyarrow as pa
from psycopg import sql

from posthog.temporal.common.logger import get_write_only_logger

from products.warehouse_destinations.backend.core.json_type import JsonType
from products.warehouse_destinations.backend.core.transformer import CSVStreamTransformer
from products.warehouse_destinations.backend.destinations.postgres.client import (
    PostgreSQLClient,
    connect_configuration_error_detail,
    host_configuration_error_detail,
    is_connect_error_retryable,
)
from products.warehouse_destinations.backend.destinations.postgres.errors import (
    PostgreSQLConnectionConfigurationError,
    PostgreSQLConnectionError,
    PostgreSQLIncompatibleSchemaError,
    PostgreSQLInvalidTargetError,
    PostgreSQLUnrelatedTableError,
)
from products.warehouse_destinations.backend.destinations.postgres.integration import resolve_client_settings
from products.warehouse_destinations.backend.destinations.postgres.types import (
    PostgresColumn,
    is_nested_type,
    resolve_columns,
)
from products.warehouse_destinations.backend.facade.contracts import (
    DestinationConnection,
    DestinationLogger,
    PreparedTarget,
    TableTarget,
    WriteOutcome,
)
from products.warehouse_destinations.backend.facade.enums import NewColumnPolicy, WriteMode

BATCH_KEY_COLUMN = "_ph_batch_key"
ROW_ID_COLUMN = "_ph_row_id"
HIDDEN_COLUMNS = frozenset({BATCH_KEY_COLUMN, ROW_ID_COLUMN})

# Postgres silently truncates a longer identifier. A truncated staging name could then match
# the final table or the staging table of another key.
MAX_IDENTIFIER_BYTES = 63
_HASH_LENGTH = 8


def scoped_identifier(base: str, suffix: str) -> str:
    """Return `base` + `suffix`, or a deterministic name of at most 63 bytes when that is longer.

    The long form keeps a prefix and appends a hash of the full name, so two long names that
    share a prefix still differ.
    """
    candidate = f"{base}{suffix}"
    encoded = candidate.encode()
    if len(encoded) <= MAX_IDENTIFIER_BYTES:
        return candidate

    digest = hashlib.sha256(encoded).hexdigest()[:_HASH_LENGTH]
    prefix = encoded[: MAX_IDENTIFIER_BYTES - _HASH_LENGTH - 1].decode(errors="ignore")
    return f"{prefix}_{digest}"


def staging_table_name(table_name: str, staging_key: str) -> str:
    return scoped_identifier(table_name, f"__ph_stage_{staging_key}")


def _is_tagged(comment: str | None, owner_tag: str) -> bool:
    # A tag can be followed by more ":"-separated segments. Compare the full segment, so that
    # tag "abc" does not match a comment that starts with "abc123".
    return comment is not None and (comment == owner_tag or comment.startswith(f"{owner_tag}:"))


def _to_json_text(value: typing.Any, *, from_map: bool) -> str | None:
    if value is None:
        return None
    if from_map:
        # A map value reads back as a list of key and value pairs.
        value = dict(value)
    # Dates, decimals and binaries can sit inside a struct, and none of them are JSON types.
    return json.dumps(value, default=str)


def _encode_column(array: pa.Array, destination_type: str) -> pa.Array:
    """Make a column readable for the CSV transformer and for Postgres.

    The transformer renders a list as a Postgres array literal and any other value with `str()`.
    That is correct for scalars and array columns, but not for JSON or BYTEA.
    """
    if pa.types.is_dictionary(array.type):
        array = typing.cast(pa.DictionaryArray, array).dictionary_decode()

    if isinstance(array.type, JsonType):
        return typing.cast(pa.ExtensionArray, array).storage

    arrow_type = array.type
    if is_nested_type(arrow_type):
        is_list = pa.types.is_list(arrow_type) or pa.types.is_large_list(arrow_type)
        if is_list and destination_type.endswith("[]"):
            return array
        from_map = pa.types.is_map(arrow_type)
        return pa.array([_to_json_text(value, from_map=from_map) for value in array.to_pylist()], type=pa.string())

    if pa.types.is_binary(arrow_type) or pa.types.is_large_binary(arrow_type):
        return pa.array(
            [None if value is None else f"\\x{value.hex()}" for value in array.to_pylist()], type=pa.string()
        )

    if pa.types.is_duration(arrow_type):
        return pa.array(
            [
                None if value is None else f"{value // dt.timedelta(microseconds=1)} microseconds"
                for value in array.to_pylist()
            ],
            type=pa.string(),
        )

    return array


def _copy_batch(
    batch: pa.RecordBatch, data_columns: list[str], table_columns: dict[str, str], batch_key: str | None
) -> pa.RecordBatch:
    arrays: list[pa.Array] = []
    for name in data_columns:
        index = batch.schema.get_field_index(name)
        if index < 0:
            arrays.append(pa.nulls(batch.num_rows, pa.string()))
        else:
            arrays.append(_encode_column(batch.column(index), table_columns[name]))

    names = list(data_columns)
    if batch_key is not None:
        arrays.append(pa.array([batch_key] * batch.num_rows, type=pa.string()))
        names.append(BATCH_KEY_COLUMN)

    return pa.RecordBatch.from_arrays(arrays, names=names)


class PostgresDestination:
    """The `Destination` for Postgres."""

    destination_type = "Postgres"

    def __init__(
        self,
        connection: DestinationConnection,
        *,
        logger: DestinationLogger | None = None,
        upload_chunk_size_bytes: int | None = None,
    ) -> None:
        self._connection = connection
        self._logger: DestinationLogger = logger or get_write_only_logger(__name__)
        self._upload_chunk_size_bytes = (
            upload_chunk_size_bytes
            if upload_chunk_size_bytes is not None
            else settings.BATCH_EXPORT_POSTGRES_UPLOAD_CHUNK_SIZE_BYTES
        )
        self._client: PostgreSQLClient | None = None

    @contextlib.asynccontextmanager
    async def connect(self) -> collections.abc.AsyncIterator[None]:
        client_settings = await resolve_client_settings(self._connection)
        client = PostgreSQLClient(
            user=client_settings.user,
            password=client_settings.password,
            host=client_settings.host,
            port=client_settings.port,
            database=client_settings.database,
            ssl_mode=client_settings.ssl_mode,
            ssl_root_cert=client_settings.ssl_root_cert,
            logger=self._logger,
        )

        # This check resolves the host only to classify it. `client.connect()` resolves it again,
        # checks those addresses, and dials only them.
        host_detail = await host_configuration_error_detail(client.host, client.port)
        if host_detail is not None:
            raise PostgreSQLConnectionConfigurationError(host_detail)

        async with contextlib.AsyncExitStack() as stack:
            # Entered apart from the body, so that only a failure to connect is classified here,
            # never an error the caller raises while it holds the connection.
            try:
                await stack.enter_async_context(client.connect(is_error_retryable=is_connect_error_retryable))
            except PostgreSQLConnectionError as err:
                # The SSRF check refused the host. Its message does not say which check failed.
                if isinstance(err.__cause__, ValueError):
                    raise PostgreSQLConnectionConfigurationError(str(err)) from err
                detail = connect_configuration_error_detail(err.__cause__) if err.__cause__ else None
                if detail is not None:
                    raise PostgreSQLConnectionConfigurationError(detail) from err
                raise

            self._client = client
            try:
                yield
            finally:
                self._client = None

    def _require_client(self) -> PostgreSQLClient:
        if self._client is None:
            raise PostgreSQLConnectionError("Not connected, enter connect() first")
        return self._client

    def _schema_of(self, target: TableTarget, client: PostgreSQLClient) -> str:
        if len(target.namespace) != 2:
            raise PostgreSQLInvalidTargetError("A Postgres namespace must be (database, schema)")

        database, schema = target.namespace
        if database != client.database:
            raise PostgreSQLInvalidTargetError(
                f"The target database '{database}' is not the connected database '{client.database}'"
            )
        for name in (schema, target.table_name):
            if len(name.encode()) > MAX_IDENTIFIER_BYTES:
                raise PostgreSQLInvalidTargetError(f"'{name}' is longer than {MAX_IDENTIFIER_BYTES} bytes")
        reserved = HIDDEN_COLUMNS.intersection(target.schema.names)
        if reserved:
            raise PostgreSQLInvalidTargetError(f"Column names are reserved: {sorted(reserved)}")
        return schema

    async def prepare(self, target: TableTarget) -> PreparedTarget:
        client = self._require_client()
        schema = self._schema_of(target, client)
        table = target.table_name
        columns = resolve_columns(target.schema, target.type_policy, target.column_overrides)

        # CREATE SCHEMA needs CREATE on the database even when the schema exists, so only run it
        # for a missing schema.
        if not await client.aschema_exists(schema):
            async with client.write_cursor() as cursor:
                await cursor.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))

        existing = await client.aget_table_columns(schema, table)
        existing_columns = tuple(existing) if existing is not None else ()

        if target.write_mode == WriteMode.REPLACE:
            if existing is not None:
                await self._check_owner(client, schema, table, target.owner_tag)
        elif existing is None:
            primary_key = target.merge.primary_keys if target.merge is not None else None
            await client.acreate_table(schema, table, columns, primary_key=primary_key)
            await self._tag(client, schema, table, target.owner_tag)
        else:
            await self._apply_new_columns(client, schema, table, columns, existing, target.new_columns)

        database = target.namespace[0]
        if target.write_mode == WriteMode.APPEND:
            return PreparedTarget(
                target=target, write_into=(database, schema, table), existing_columns=existing_columns
            )

        assert target.staging_key is not None
        staging = staging_table_name(table, target.staging_key)
        staging_existing = await client.aget_table_columns(schema, staging)
        if staging_existing is not None:
            await self._check_owner(client, schema, staging, target.owner_tag)

        if target.write_mode == WriteMode.MERGE:
            await self._prepare_merge_staging(client, schema, table, staging, columns)
        else:
            await self._prepare_replace_staging(client, schema, staging, columns, staging_existing, target.owner_tag)

        return PreparedTarget(target=target, write_into=(database, schema, staging), existing_columns=existing_columns)

    async def _apply_new_columns(
        self,
        client: PostgreSQLClient,
        schema: str,
        table: str,
        columns: tuple[PostgresColumn, ...],
        existing: dict[str, str],
        policy: NewColumnPolicy,
    ) -> None:
        if policy == NewColumnPolicy.IGNORE:
            if not any(column.name in existing for column in columns):
                raise PostgreSQLIncompatibleSchemaError(
                    f"No matching columns found in the destination table '{schema}.{table}'"
                )
            return

        await self._add_missing_columns(client, schema, table, [c for c in columns if c.name not in existing])

    async def _add_missing_columns(
        self, client: PostgreSQLClient, schema: str, table: str, columns: collections.abc.Sequence[PostgresColumn]
    ) -> None:
        for column in columns:
            async with client.write_cursor() as cursor:
                await cursor.execute(
                    sql.SQL("ALTER TABLE {} ADD COLUMN IF NOT EXISTS {} {}").format(
                        sql.Identifier(schema, table), sql.Identifier(column.name), sql.SQL(column.type)
                    )
                )

    async def _prepare_merge_staging(
        self,
        client: PostgreSQLClient,
        schema: str,
        table: str,
        staging: str,
        columns: tuple[PostgresColumn, ...],
    ) -> None:
        # Copied from the final table (`LIKE`), so a column has the same type in both tables even
        # when the final table predates this write.
        async with client.write_cursor() as cursor:
            await cursor.execute(
                sql.SQL("CREATE TABLE IF NOT EXISTS {} (LIKE {})").format(
                    sql.Identifier(schema, staging), sql.Identifier(schema, table)
                )
            )
            await cursor.execute(
                sql.SQL(
                    "ALTER TABLE {} ADD COLUMN IF NOT EXISTS {} TEXT, "
                    "ADD COLUMN IF NOT EXISTS {} BIGINT GENERATED BY DEFAULT AS IDENTITY"
                ).format(
                    sql.Identifier(schema, staging), sql.Identifier(BATCH_KEY_COLUMN), sql.Identifier(ROW_ID_COLUMN)
                )
            )

        # A resumed attempt finds the staging table of an earlier attempt, which lacks columns
        # added to the final table since then.
        final_columns = await client.aget_table_columns(schema, table) or {}
        staging_columns = await client.aget_table_columns(schema, staging) or {}
        await self._add_missing_columns(
            client,
            schema,
            staging,
            [c for c in columns if c.name in final_columns and c.name not in staging_columns],
        )

    async def _prepare_replace_staging(
        self,
        client: PostgreSQLClient,
        schema: str,
        staging: str,
        columns: tuple[PostgresColumn, ...],
        staging_existing: dict[str, str] | None,
        owner_tag: str | None,
    ) -> None:
        if staging_existing is None:
            await client.acreate_table(schema, staging, [*columns, PostgresColumn(name=BATCH_KEY_COLUMN, type="TEXT")])
            await self._tag(client, schema, staging, owner_tag)
            return

        await self._add_missing_columns(
            client,
            schema,
            staging,
            [
                *(c for c in columns if c.name not in staging_existing),
                *(
                    [PostgresColumn(name=BATCH_KEY_COLUMN, type="TEXT")]
                    if BATCH_KEY_COLUMN not in staging_existing
                    else []
                ),
            ],
        )

    async def _check_owner(self, client: PostgreSQLClient, schema: str, table: str, owner_tag: str | None) -> None:
        if owner_tag is None:
            return
        if not _is_tagged(await client.aget_table_comment(schema, table), owner_tag):
            raise PostgreSQLUnrelatedTableError(
                f"'{schema}.{table}' already exists and was not created by this caller; refusing to replace or reuse it"
            )

    async def _tag(self, client: PostgreSQLClient, schema: str, table: str, owner_tag: str | None) -> None:
        if owner_tag is None:
            return
        async with client.write_cursor() as cursor:
            # COMMENT ON takes only a string literal, not a bind parameter. `sql.Literal` quotes it.
            await cursor.execute(
                sql.SQL("COMMENT ON TABLE {} IS {}").format(sql.Identifier(schema, table), sql.Literal(owner_tag))
            )

    async def write(
        self,
        prepared: PreparedTarget,
        batches: collections.abc.AsyncIterable[pa.RecordBatch],
        *,
        batch_key: str | None = None,
    ) -> WriteOutcome:
        client = self._require_client()
        target = prepared.target
        if batch_key is not None and target.write_mode == WriteMode.APPEND:
            raise ValueError(
                "A batch key needs a staging table, and an APPEND write goes straight into the final table"
            )

        _, schema, table = prepared.write_into
        table_columns = await client.aget_table_columns(schema, table)
        if table_columns is None:
            raise PostgreSQLIncompatibleSchemaError(f"The table '{schema}.{table}' does not exist")

        # Under NewColumnPolicy.IGNORE the table can lack some incoming columns. Those are dropped.
        data_columns = [name for name in target.schema.names if name in table_columns]
        if not data_columns:
            raise PostgreSQLIncompatibleSchemaError(
                f"No matching columns found in the destination table '{schema}.{table}'"
            )

        if batch_key is not None:
            async with client.write_cursor() as cursor:
                await cursor.execute(
                    sql.SQL("DELETE FROM {} WHERE {} = %s").format(
                        sql.Identifier(schema, table), sql.Identifier(BATCH_KEY_COLUMN)
                    ),
                    (batch_key,),
                )

        field_names = [*data_columns, *([BATCH_KEY_COLUMN] if batch_key is not None else [])]
        # The COPY reads CSV with a tab delimiter, and Postgres CSV has no backslash escape. A
        # value with a tab, a newline or a double quote survives only when the writer quotes it.
        transformer = CSVStreamTransformer(
            field_names=field_names,
            delimiter="\t",
            quote_char='"',
            escape_char=None,
            line_terminator="\n",
            quoting=csv.QUOTE_STRINGS,
            include_inserted_at=True,
            max_file_size_bytes=self._upload_chunk_size_bytes,
        )

        rows_written = 0

        async def copy_batches() -> collections.abc.AsyncIterator[pa.RecordBatch]:
            nonlocal rows_written
            async for batch in batches:
                if batch.num_rows == 0:
                    continue
                rows_written += batch.num_rows
                yield _copy_batch(batch, data_columns, table_columns, batch_key)

        bytes_written = 0
        buffer = io.BytesIO()
        async for chunk in transformer.iter(copy_batches()):
            buffer.write(chunk.data)
            bytes_written += len(chunk.data)
            if chunk.is_eof and buffer.tell():
                await client.copy_tsv_to_postgres(buffer, schema, table, field_names)
                buffer = io.BytesIO()

        return WriteOutcome(rows_written=rows_written, bytes_written=bytes_written)

    async def commit(self, prepared: PreparedTarget) -> None:
        client = self._require_client()
        target = prepared.target
        if target.write_mode == WriteMode.APPEND:
            return

        _, schema, staging = prepared.write_into
        # The commit drops the staging table in its own transaction, so a missing staging
        # table means an earlier commit finished.
        staging_columns = await client.aget_table_columns(schema, staging)
        if staging_columns is None:
            return

        if target.write_mode == WriteMode.MERGE:
            await self._merge(client, target, schema, staging, staging_columns)
        else:
            await self._swap(client, target, schema, staging)

    async def _merge(
        self, client: PostgreSQLClient, target: TableTarget, schema: str, staging: str, staging_columns: dict[str, str]
    ) -> None:
        merge = target.merge
        assert merge is not None
        table = target.table_name

        final_columns = await client.aget_table_columns(schema, table)
        if final_columns is None:
            raise PostgreSQLIncompatibleSchemaError(f"The table '{schema}.{table}' does not exist")
        columns = [name for name in target.schema.names if name in final_columns and name in staging_columns]

        if not merge.version_keys and not await client.ahas_unique_index_on(schema, table, merge.primary_keys):
            # ON CONFLICT needs a unique constraint on the keys. A table this destination created
            # has one as its primary key, but a table the customer created may not.
            async with client.write_cursor() as cursor:
                await cursor.execute(
                    sql.SQL("CREATE UNIQUE INDEX IF NOT EXISTS {} ON {} ({})").format(
                        sql.Identifier(scoped_identifier(table, "__ph_pk")),
                        sql.Identifier(schema, table),
                        sql.SQL(", ").join(map(sql.Identifier, merge.primary_keys)),
                    )
                )

        dedupe_order_by = None
        if merge.dedupe_source:
            dedupe_order_by = sql.SQL(", ").join(
                [
                    *map(sql.Identifier, merge.primary_keys),
                    *(sql.SQL("{} DESC NULLS LAST").format(sql.Identifier(key)) for key in merge.version_keys),
                    sql.SQL("{} DESC").format(sql.Identifier(ROW_ID_COLUMN)),
                ]
            )

        await client.amerge_mutable_tables(
            schema=schema,
            final_table_name=table,
            stage_table_name=staging,
            merge_key=merge.primary_keys,
            update_key=merge.version_keys,
            columns=columns,
            dedupe_order_by=dedupe_order_by,
            drop_stage=True,
        )

    async def _swap(self, client: PostgreSQLClient, target: TableTarget, schema: str, staging: str) -> None:
        table = target.table_name
        if await client.aget_table_columns(schema, table) is not None:
            await self._check_owner(client, schema, table, target.owner_tag)

        async with client.write_cursor() as cursor:
            await cursor.execute(
                sql.SQL("ALTER TABLE {} DROP COLUMN IF EXISTS {}").format(
                    sql.Identifier(schema, staging), sql.Identifier(BATCH_KEY_COLUMN)
                )
            )
            await cursor.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(schema, table)))
            await cursor.execute(
                sql.SQL("ALTER TABLE {} RENAME TO {}").format(sql.Identifier(schema, staging), sql.Identifier(table))
            )
            if target.owner_tag is not None:
                await cursor.execute(
                    sql.SQL("COMMENT ON TABLE {} IS {}").format(
                        sql.Identifier(schema, table), sql.Literal(target.owner_tag)
                    )
                )

    async def abort(self, prepared: PreparedTarget) -> None:
        if prepared.target.write_mode == WriteMode.APPEND:
            return
        try:
            client = self._require_client()
            _, schema, staging = prepared.write_into
            await client.adelete_table(schema, staging, not_found_ok=True)
        except Exception:
            self._logger.warning("Failed to drop the staging table", exc_info=True)
