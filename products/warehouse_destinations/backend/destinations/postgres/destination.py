"""Write Arrow record batches into a Postgres table.

The connection's `PostgresDestinationConfig` picks the database, and the namespace of a target is
`(schema,)`. `spec.py` declares the settings, and `integration.py` reads them.

- APPEND copies rows straight into the final table.
- MERGE copies rows into a staging table. A commit upserts the staging rows into the final table
  on the primary keys, then empties (`final=False`) or drops (`final=True`) the staging table in
  the same transaction.
- REPLACE copies rows into a staging table. The final commit swaps it into the final name in one
  transaction, so readers see the old table right up to the moment the new one is complete.

A write commits each chunk on its own, so a failed write can leave some chunks of its rows in the
staging table. A staging table carries a batch-key column, so a retry with the same batch key
removes those rows first. A MERGE staging table also carries a row id, so `dedupe_source` keeps
the last written row of each key. Each staging table carries a `TableMarker` in its comment with
the settings a commit needs, so a commit needs only the `TargetRef`. A final table that a REPLACE
committed carries the staging key in its marker, so a replay finds that it already committed.

Every driver error that leaves a session method becomes a `DestinationError` (see `errors.py`).
"""

import io
import csv
import json
import typing
import asyncio
import hashlib
import datetime as dt
import functools
import contextlib
import collections.abc
from types import MappingProxyType

from django.conf import settings

import orjson
import psycopg
import pyarrow as pa
from psycopg import sql
from psycopg.adapt import Transformer
from psycopg.types.array import ListDumper

from posthog.dataclasses import frozen

from products.warehouse_destinations.backend.core import table_marker
from products.warehouse_destinations.backend.core.json_type import is_json_type, load_json
from products.warehouse_destinations.backend.core.loggers import get_write_only_logger
from products.warehouse_destinations.backend.core.table_marker import TableMarker
from products.warehouse_destinations.backend.core.transformer import CSVStreamTransformer
from products.warehouse_destinations.backend.core.validation import check_batch_key, check_ref
from products.warehouse_destinations.backend.destinations.postgres.capabilities import POSTGRES_CAPABILITIES
from products.warehouse_destinations.backend.destinations.postgres.client import (
    PostgreSQLClient,
    connect_configuration_error_detail,
    host_configuration_error_detail,
    is_connect_error_retryable,
)
from products.warehouse_destinations.backend.destinations.postgres.errors import (
    MissingPrimaryKeyError,
    PostgreSQLConnectionConfigurationError,
    PostgreSQLConnectionError,
    PostgreSQLIncompatibleSchemaError,
    PostgreSQLInvalidTargetError,
    PostgreSQLLockTimeoutError,
    PostgreSQLUnrelatedTableError,
    translate_error,
)
from products.warehouse_destinations.backend.destinations.postgres.integration import resolve_client_settings
from products.warehouse_destinations.backend.destinations.postgres.types import (
    PostgresColumn,
    is_nested_type,
    resolve_columns,
)
from products.warehouse_destinations.backend.facade.contracts import (
    DestinationCapabilities,
    DestinationConfigurationError,
    DestinationConnection,
    DestinationLogger,
    MergeSpec,
    PreparedTarget,
    TableTarget,
    TargetRef,
    WriteOutcome,
)
from products.warehouse_destinations.backend.facade.enums import (
    DestinationType,
    ExistingTablePolicy,
    LogicalType,
    NewColumnPolicy,
    WriteMode,
)

_P = typing.ParamSpec("_P")
_R = typing.TypeVar("_R")

BATCH_KEY_COLUMN = "_ph_batch_key"
ROW_ID_COLUMN = "_ph_row_id"
HIDDEN_COLUMNS = frozenset({BATCH_KEY_COLUMN, ROW_ID_COLUMN})

# Postgres silently truncates a longer identifier. A truncated staging name could then match
# the final table or the staging table of another key.
MAX_IDENTIFIER_BYTES = 63
_HASH_LENGTH = 8
_STAGING_HASH_LENGTH = 16


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
    """Return the staging table of `staging_key`, a deterministic name of at most 63 bytes.

    Both parts can contain the separator, so the readable prefix alone is ambiguous:
    `("a", "b__ph_stage_c")` and `("a__ph_stage_b", "c")` read the same. The hash covers a JSON
    encoding of the pair, which keeps the parts apart, so two pairs get distinct names.
    """
    digest = hashlib.sha256(json.dumps([table_name, staging_key]).encode()).hexdigest()[:_STAGING_HASH_LENGTH]
    readable = f"{table_name}__ph_stage_{staging_key}".encode()
    prefix = readable[: MAX_IDENTIFIER_BYTES - _STAGING_HASH_LENGTH - 1].decode(errors="ignore")
    return f"{prefix}_{digest}"


def batch_key_index_name(staging: str) -> str:
    return scoped_identifier(staging, "__ph_bk")


def _lock_key(schema: str, table: str) -> str:
    return f"posthog_destination:{sql.Identifier(schema, table).as_string()}"


def _pg_array_literal(values: list[typing.Any]) -> str:
    """Render a list as a Postgres array literal, nested lists included."""
    dumped = ListDumper(list, Transformer()).dump(values)
    assert dumped is not None
    return bytes(dumped).decode("utf-8")


def _to_json_text(value: typing.Any, *, from_map: bool) -> str | None:
    if value is None:
        return None
    if from_map:
        # A map value reads back as a list of key and value pairs.
        value = dict(value)
    # Dates, decimals and binaries can sit inside a struct, and none of them are JSON types.
    return json.dumps(value, default=str)


def _normalize_json_text(value: str | None) -> str | None:
    """Repair a JSON text with `load_json`, then encode it again, so that Postgres accepts it."""
    if value is None:
        return None
    decoded = load_json(value)
    if decoded is None:
        # An empty text has no JSON value. The text "null" is the JSON null.
        return "null" if value else None
    return json.dumps(decoded, default=str)


def _encode_column(array: pa.Array, column_type: str, *, as_json: bool) -> pa.Array:
    """Make a column readable for the CSV transformer and for Postgres.

    The transformer renders a list as a Postgres array literal and any other value with `str()`.
    That is correct for scalars and array columns, but not for JSON or BYTEA.
    """
    if pa.types.is_dictionary(array.type):
        array = typing.cast(pa.DictionaryArray, array).dictionary_decode()

    if is_json_type(array.type):
        storage = typing.cast(pa.ExtensionArray, array).storage
        return pa.array([_normalize_json_text(value) for value in storage.to_pylist()], type=pa.string())

    arrow_type = array.type
    if is_nested_type(arrow_type):
        is_list = pa.types.is_list(arrow_type) or pa.types.is_large_list(arrow_type)
        if is_list and column_type.endswith("[]") and not as_json:
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


@frozen
class _PreparedState:
    """What `prepare` learned, kept on the `PreparedTarget` so `write` reads no catalog."""

    schema: str
    write_into: str
    # Name to Postgres type, in table order.
    columns: collections.abc.Mapping[str, str]


def _translate_errors(
    method: typing.Callable[_P, collections.abc.Awaitable[_R]],
) -> typing.Callable[_P, collections.abc.Coroutine[typing.Any, typing.Any, _R]]:
    """Let a `DestinationError` from `method` pass unchanged, and translate any other exception.

    The translated error is a `DestinationError` raised from the original exception.
    """

    @functools.wraps(method)
    async def inner(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        try:
            return await method(*args, **kwargs)
        except Exception as err:
            translated = translate_error(err)
            if translated is err:
                raise
            raise translated from err

    return inner


class PostgresSession:
    """The `DestinationSession` for Postgres. One per `PostgresDestination.connect()` context."""

    def __init__(
        self,
        client: PostgreSQLClient,
        *,
        capabilities: DestinationCapabilities,
        logger: DestinationLogger,
        upload_chunk_size_bytes: int,
        swap_lock_timeout_seconds: float,
    ) -> None:
        self._pg: PostgreSQLClient | None = client
        self._capabilities = capabilities
        self._logger = logger
        self._upload_chunk_size_bytes = upload_chunk_size_bytes
        self._swap_lock_timeout_seconds = swap_lock_timeout_seconds

    def close(self) -> None:
        self._pg = None

    def _client(self) -> PostgreSQLClient:
        if self._pg is None:
            raise DestinationConfigurationError("The session is closed; open a new one with connect()")
        return self._pg

    @_translate_errors
    async def prepare(self, target: TableTarget) -> PreparedTarget:
        client = self._client()
        ref = target.ref
        check_ref(self._capabilities, ref)
        schema = self._schema_of(target)
        table = ref.table_name
        columns = resolve_columns(target.schema, target.type_policy, target.column_types)

        # CREATE SCHEMA needs CREATE on the database even when the schema exists, so only run it
        # for a missing schema. The lock stops concurrent sessions from racing on the catalog.
        if not await client.aschema_exists(schema):
            async with client.write_cursor() as cursor:
                await client.advisory_lock(cursor, f"posthog_destination:{sql.Identifier(schema).as_string()}")
                await cursor.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))

        final_columns = await client.aget_table_columns(schema, table)
        if final_columns is not None:
            final_comment = await client.aget_table_comment(schema, table)
            if target.existing_table == ExistingTablePolicy.REQUIRE_OWNED:
                _check_owned(schema, table, final_comment, ref.owner_tag)
            if ref.write_mode == WriteMode.REPLACE and _committed_by(final_comment, ref):
                return PreparedTarget(target=target, already_committed=True)

        if ref.write_mode != WriteMode.REPLACE:
            if final_columns is None:
                await client.acreate_table(
                    schema,
                    table,
                    columns,
                    primary_key=target.merge.primary_keys if target.merge is not None else None,
                    comment=TableMarker(owner_tag=ref.owner_tag).encode() if ref.owner_tag is not None else None,
                    lock_key=_lock_key(schema, table),
                )
            else:
                await self._apply_new_columns(client, schema, table, columns, final_columns, target.new_columns)
                if target.merge is not None:
                    await self._ensure_unique_key(client, schema, table, target.merge)

        if ref.write_mode == WriteMode.APPEND:
            write_into = table
        else:
            assert ref.staging_key is not None
            write_into = staging_table_name(table, ref.staging_key)
            marker = TableMarker(
                owner_tag=ref.owner_tag,
                require_owned=target.existing_table == ExistingTablePolicy.REQUIRE_OWNED,
                merge=target.merge,
            )
            await self._prepare_staging(client, ref, schema, write_into, columns, marker)

        write_columns = await client.aget_table_columns(schema, write_into)
        if write_columns is None:
            raise PostgreSQLIncompatibleSchemaError(f"The table '{schema}.{write_into}' does not exist")
        state = _PreparedState(schema=schema, write_into=write_into, columns=MappingProxyType(write_columns))
        return PreparedTarget(target=target, internal=state)

    def _schema_of(self, target: TableTarget) -> str:
        (schema,) = target.ref.namespace
        for name in (schema, target.ref.table_name):
            if len(name.encode()) > MAX_IDENTIFIER_BYTES:
                raise PostgreSQLInvalidTargetError(f"'{name}' is longer than {MAX_IDENTIFIER_BYTES} bytes")
        reserved = HIDDEN_COLUMNS.intersection(target.schema.names)
        if reserved:
            raise PostgreSQLInvalidTargetError(f"Column names are reserved: {sorted(reserved)}")
        # Postgres would truncate the name, and later writes would not find the column.
        too_long = [name for name in target.schema.names if len(name.encode()) > MAX_IDENTIFIER_BYTES]
        if too_long:
            raise PostgreSQLIncompatibleSchemaError(
                f"column names are longer than {MAX_IDENTIFIER_BYTES} bytes: {sorted(too_long)}"
            )
        return schema

    async def _apply_new_columns(
        self,
        client: PostgreSQLClient,
        schema: str,
        table: str,
        columns: tuple[PostgresColumn, ...],
        existing: collections.abc.Mapping[str, str],
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
        # A type comes from the fixed mappings in `types.py`, or from `format_type` in the
        # destination's catalog, which quotes any name in it. Never from caller text.
        for column in columns:
            async with client.write_cursor() as cursor:
                await cursor.execute(
                    sql.SQL("ALTER TABLE {} ADD COLUMN IF NOT EXISTS {} {}").format(
                        sql.Identifier(schema, table), sql.Identifier(column.name), sql.SQL(column.type)
                    )
                )

    async def _ensure_unique_key(self, client: PostgreSQLClient, schema: str, table: str, merge: MergeSpec) -> None:
        # ON CONFLICT needs a unique key on exactly the merge keys. A table this destination
        # created has one as its primary key, but a table someone else created may not.
        if await client.ahas_unique_index_on(schema, table, merge.primary_keys):
            return
        if not merge.ensure_unique_key:
            raise MissingPrimaryKeyError(f"{schema}.{table}", merge.primary_keys)

        async with client.write_cursor() as cursor:
            await cursor.execute(
                sql.SQL("CREATE UNIQUE INDEX IF NOT EXISTS {} ON {} ({})").format(
                    sql.Identifier(scoped_identifier(table, "__ph_pk")),
                    sql.Identifier(schema, table),
                    sql.SQL(", ").join(map(sql.Identifier, merge.primary_keys)),
                )
            )

    async def _prepare_staging(
        self,
        client: PostgreSQLClient,
        ref: TargetRef,
        schema: str,
        staging: str,
        columns: tuple[PostgresColumn, ...],
        marker: TableMarker,
    ) -> None:
        existing = await client.aget_table_columns(schema, staging)
        stored: TableMarker | None = None
        if existing is not None:
            stored = table_marker.parse(await client.aget_table_comment(schema, staging))
            if stored is None or stored.owner_tag != ref.owner_tag:
                raise PostgreSQLUnrelatedTableError(
                    f"'{schema}.{staging}' already exists and was not staged for this target; refusing to reuse it"
                )

        if ref.write_mode == WriteMode.MERGE:
            # Copied from the final table (`LIKE`), so a column has the same type in both tables
            # even when the final table predates this write.
            async with client.write_cursor() as cursor:
                await client.advisory_lock(cursor, _lock_key(schema, staging))
                await cursor.execute(
                    sql.SQL("CREATE TABLE IF NOT EXISTS {} (LIKE {})").format(
                        sql.Identifier(schema, staging), sql.Identifier(schema, ref.table_name)
                    )
                )
                await cursor.execute(
                    sql.SQL(
                        "ALTER TABLE {} ADD COLUMN IF NOT EXISTS {} TEXT, "
                        "ADD COLUMN IF NOT EXISTS {} BIGINT GENERATED BY DEFAULT AS IDENTITY"
                    ).format(
                        sql.Identifier(schema, staging),
                        sql.Identifier(BATCH_KEY_COLUMN),
                        sql.Identifier(ROW_ID_COLUMN),
                    )
                )
                if stored != marker:
                    await client.set_comment(cursor, schema, staging, marker.encode())
                await _create_batch_key_index(cursor, schema, staging)

            # A resumed attempt finds the staging table of an earlier attempt, which lacks columns
            # added to the final table since then. Each gets the final table's type, as `LIKE`
            # would have given it, so that the merge reads the same type it writes.
            final_columns = await client.aget_table_columns(schema, ref.table_name) or {}
            staging_columns = await client.aget_table_columns(schema, staging) or {}
            await self._add_missing_columns(
                client,
                schema,
                staging,
                [
                    PostgresColumn(name=c.name, type=final_columns[c.name])
                    for c in columns
                    if c.name in final_columns and c.name not in staging_columns
                ],
            )
            return

        batch_key_column = PostgresColumn(name=BATCH_KEY_COLUMN, type="TEXT")
        if existing is None:
            await client.acreate_table(
                schema,
                staging,
                [*columns, batch_key_column],
                comment=marker.encode(),
                lock_key=_lock_key(schema, staging),
            )
        else:
            await self._add_missing_columns(
                client,
                schema,
                staging,
                [c for c in (*columns, batch_key_column) if c.name not in existing],
            )
            if stored != marker:
                async with client.write_cursor() as cursor:
                    await client.set_comment(cursor, schema, staging, marker.encode())

        async with client.write_cursor() as cursor:
            await client.advisory_lock(cursor, _lock_key(schema, staging))
            await _create_batch_key_index(cursor, schema, staging)

    @_translate_errors
    async def write(
        self,
        prepared: PreparedTarget,
        batches: collections.abc.AsyncIterable[pa.RecordBatch],
        *,
        batch_key: str | None = None,
    ) -> WriteOutcome:
        client = self._client()
        target = prepared.target
        check_batch_key(self._capabilities, target.ref, batch_key)
        if prepared.already_committed:
            return WriteOutcome(rows_written=0, bytes_written=0)

        state = prepared.internal
        if not isinstance(state, _PreparedState):
            raise DestinationConfigurationError("The prepared target does not come from a Postgres session")
        schema, table = state.schema, state.write_into

        # Under NewColumnPolicy.IGNORE the table can lack some incoming columns. Those are dropped.
        data_columns = [name for name in target.schema.names if name in state.columns]
        if not data_columns:
            raise PostgreSQLIncompatibleSchemaError(
                f"No matching columns found in the destination table '{schema}.{table}'"
            )
        json_columns = {name for name, logical in target.column_types.items() if logical == LogicalType.JSON}

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
            max_file_size_bytes=self._upload_chunk_size_bytes,
            list_formatter=_pg_array_literal,
        )

        rows_written = 0

        def copy_batch(batch: pa.RecordBatch) -> pa.RecordBatch:
            arrays: list[pa.Array] = []
            for name in data_columns:
                index = batch.schema.get_field_index(name)
                if index < 0:
                    arrays.append(pa.nulls(batch.num_rows, pa.string()))
                    continue
                try:
                    arrays.append(
                        _encode_column(batch.column(index), state.columns[name], as_json=name in json_columns)
                    )
                except orjson.JSONDecodeError as err:
                    raise PostgreSQLIncompatibleSchemaError(
                        f"a value in the JSON column '{name}' is not valid JSON"
                    ) from err
            names = list(data_columns)
            if batch_key is not None:
                arrays.append(pa.array([batch_key] * batch.num_rows, type=pa.string()))
                names.append(BATCH_KEY_COLUMN)
            return pa.RecordBatch.from_arrays(arrays, names=names)

        async def copy_batches() -> collections.abc.AsyncIterator[pa.RecordBatch]:
            nonlocal rows_written
            async for batch in batches:
                if batch.num_rows == 0:
                    continue
                rows_written += batch.num_rows
                # Encoding walks every value in Python, so it runs off the event loop.
                yield await asyncio.to_thread(copy_batch, batch)

        bytes_written = 0
        buffer = io.BytesIO()
        async for chunk in transformer.iter(copy_batches()):
            buffer.write(chunk.data)
            bytes_written += len(chunk.data)
            if chunk.is_eof and buffer.tell():
                await client.copy_tsv_to_postgres(buffer, schema, table, field_names)
                buffer = io.BytesIO()

        return WriteOutcome(rows_written=rows_written, bytes_written=bytes_written)

    @_translate_errors
    async def commit(self, ref: TargetRef, *, final: bool = True) -> None:
        client = self._client()
        check_ref(self._capabilities, ref)
        if ref.write_mode == WriteMode.APPEND or (ref.write_mode == WriteMode.REPLACE and not final):
            return

        (schema,) = ref.namespace
        assert ref.staging_key is not None
        staging = staging_table_name(ref.table_name, ref.staging_key)
        # A missing staging table means nothing was prepared, or an earlier commit finished.
        staging_columns = await client.aget_table_columns(schema, staging)
        if staging_columns is None:
            return

        marker = table_marker.parse(await client.aget_table_comment(schema, staging))
        if marker is None or marker.owner_tag != ref.owner_tag:
            raise PostgreSQLUnrelatedTableError(
                f"'{schema}.{staging}' was not staged for this target; refusing to commit it"
            )

        if ref.write_mode == WriteMode.MERGE:
            await self._merge(client, ref, schema, staging, staging_columns, marker, final=final)
        else:
            await self._swap(client, ref, schema, staging, marker)

    async def _merge(
        self,
        client: PostgreSQLClient,
        ref: TargetRef,
        schema: str,
        staging: str,
        staging_columns: collections.abc.Mapping[str, str],
        marker: TableMarker,
        *,
        final: bool,
    ) -> None:
        merge = marker.merge
        if merge is None:
            raise PostgreSQLInvalidTargetError(
                f"'{schema}.{staging}' has no merge settings; prepare the target again before the commit"
            )
        table = ref.table_name

        final_columns = await client.aget_table_columns(schema, table)
        if final_columns is None:
            raise PostgreSQLIncompatibleSchemaError(f"The table '{schema}.{table}' does not exist")
        if marker.require_owned:
            _check_owned(schema, table, await client.aget_table_comment(schema, table), ref.owner_tag)
        columns = [name for name in final_columns if name in staging_columns and name not in HIDDEN_COLUMNS]

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
            stage_after="drop" if final else "truncate",
            lock_key=_lock_key(schema, staging),
        )

    async def _swap(
        self, client: PostgreSQLClient, ref: TargetRef, schema: str, staging: str, marker: TableMarker
    ) -> None:
        table = ref.table_name
        committed = TableMarker(owner_tag=ref.owner_tag, committed_staging_key=ref.staging_key)

        try:
            async with client.write_cursor() as cursor:
                await client.advisory_lock(cursor, _lock_key(schema, staging))
                # Another commit of the same key can have swapped while this one waited for the lock.
                if await client.aget_table_columns(schema, staging) is None:
                    return
                if marker.require_owned and await client.aget_table_columns(schema, table) is not None:
                    _check_owned(schema, table, await client.aget_table_comment(schema, table), ref.owner_tag)

                # The DROP waits for every reader of the final table, and new readers queue behind
                # it. The limit stops one long reader from stalling the commit and those readers.
                await client.set_local_lock_timeout(cursor, self._swap_lock_timeout_seconds)
                await cursor.execute(
                    sql.SQL("ALTER TABLE {} DROP COLUMN IF EXISTS {}").format(
                        sql.Identifier(schema, staging), sql.Identifier(BATCH_KEY_COLUMN)
                    )
                )
                await cursor.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(schema, table)))
                await cursor.execute(
                    sql.SQL("ALTER TABLE {} RENAME TO {}").format(
                        sql.Identifier(schema, staging), sql.Identifier(table)
                    )
                )
                await client.set_comment(cursor, schema, table, committed.encode())
        except psycopg.errors.LockNotAvailable as err:
            raise PostgreSQLLockTimeoutError(
                f"The swap into '{schema}.{table}' waited more than {self._swap_lock_timeout_seconds} seconds "
                "for a lock that another session holds"
            ) from err

    async def abort(self, ref: TargetRef) -> None:
        try:
            client = self._client()
            check_ref(self._capabilities, ref)
            if ref.write_mode == WriteMode.APPEND:
                return

            (schema,) = ref.namespace
            assert ref.staging_key is not None
            staging = staging_table_name(ref.table_name, ref.staging_key)
            if await client.aget_table_columns(schema, staging) is None:
                return

            marker = table_marker.parse(await client.aget_table_comment(schema, staging))
            if marker is None or marker.owner_tag != ref.owner_tag:
                self._logger.warning("Refused to drop a staging table that was not staged for this target")
                return
            await client.adelete_table(schema, staging, not_found_ok=True)
        except Exception:
            self._logger.warning("Failed to drop the staging table", exc_info=True)


async def _create_batch_key_index(cursor: psycopg.AsyncCursor, schema: str, staging: str) -> None:
    """Index the batch-key column, so that the delete a retried write runs reads only its rows.

    The caller holds the staging table's advisory lock, so concurrent creates do not race.
    """
    index = batch_key_index_name(staging)
    await cursor.execute("SELECT to_regclass(%s)", (sql.Identifier(schema, index).as_string(),))
    row = await cursor.fetchone()
    if row is not None and row[0] is not None:
        return
    await cursor.execute(
        sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} ({})").format(
            sql.Identifier(index), sql.Identifier(schema, staging), sql.Identifier(BATCH_KEY_COLUMN)
        )
    )


def _check_owned(schema: str, table: str, comment: str | None, owner_tag: str | None) -> None:
    if owner_tag is None or not table_marker.is_owned_by(comment, owner_tag):
        raise PostgreSQLUnrelatedTableError(
            f"'{schema}.{table}' already exists and does not carry the owner tag of this target; refusing to write to it"
        )


def _committed_by(comment: str | None, ref: TargetRef) -> bool:
    marker = table_marker.parse(comment)
    return (
        marker is not None
        and marker.committed_staging_key is not None
        and marker.committed_staging_key == ref.staging_key
        and marker.owner_tag == ref.owner_tag
    )


class PostgresDestination:
    """The `Destination` for Postgres."""

    destination_type = DestinationType.POSTGRES
    capabilities = POSTGRES_CAPABILITIES

    def __init__(
        self,
        connection: DestinationConnection,
        *,
        logger: DestinationLogger | None = None,
        upload_chunk_size_bytes: int | None = None,
        swap_lock_timeout_seconds: float | None = None,
    ) -> None:
        self._connection = connection
        self._logger: DestinationLogger = logger or get_write_only_logger(__name__)
        self._upload_chunk_size_bytes = (
            upload_chunk_size_bytes
            if upload_chunk_size_bytes is not None
            else settings.WAREHOUSE_DESTINATIONS_POSTGRES_UPLOAD_CHUNK_SIZE_BYTES
        )
        self._swap_lock_timeout_seconds = (
            swap_lock_timeout_seconds
            if swap_lock_timeout_seconds is not None
            else settings.WAREHOUSE_DESTINATIONS_POSTGRES_SWAP_LOCK_TIMEOUT_SECONDS
        )

    @contextlib.asynccontextmanager
    async def connect(self) -> collections.abc.AsyncIterator[PostgresSession]:
        async with contextlib.AsyncExitStack() as stack:
            # Only a failure to connect is translated here, never an error the caller raises
            # while it holds the session.
            try:
                client = await self._open_client(stack)
            except Exception as err:
                translated = translate_error(err)
                if translated is err:
                    raise
                raise translated from err

            session = PostgresSession(
                client,
                capabilities=self.capabilities,
                logger=self._logger,
                upload_chunk_size_bytes=self._upload_chunk_size_bytes,
                swap_lock_timeout_seconds=self._swap_lock_timeout_seconds,
            )
            try:
                yield session
            finally:
                session.close()

    async def _open_client(self, stack: contextlib.AsyncExitStack) -> PostgreSQLClient:
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
        return client
