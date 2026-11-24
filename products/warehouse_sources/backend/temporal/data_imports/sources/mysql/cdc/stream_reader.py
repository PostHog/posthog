"""Reads row changes from a MySQL server's binary log, from the position PostHog holds.

Each read opens a non-blocking binlog dump at the confirmed position and stops at the end of the log.
Nothing on the server tracks what PostHog has read, so `confirm_position` stores the position on the
source, and a read that is not confirmed is read again by the next one, as a Postgres peek is.
"""

from __future__ import annotations

import re
import datetime as dt
import zoneinfo
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import ExitStack
from typing import TYPE_CHECKING, Any

import pymysql
import structlog
from pymysqlreplication import BinLogStreamReader
from pymysqlreplication.event import QueryEvent, XidEvent
from pymysqlreplication.row_event import (
    DeleteRowsEvent,
    PartialUpdateRowsEvent,
    RowsEvent,
    UpdateRowsEvent,
    WriteRowsEvent,
)

from products.warehouse_sources.backend.temporal.data_imports.cdc.errors import CDCStreamNotConfiguredError
from products.warehouse_sources.backend.temporal.data_imports.cdc.types import ChangeEvent
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc import binlog
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.adapter import (
    MANAGEMENT_READ_TIMEOUT_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.config import (
    POSITION_KEY,
    MySQLCDCConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.errors import (
    MySQLUnsupportedBinlogError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.position import BinlogPosition
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.transaction_buffer import (
    TransactionBuffer,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.values import TableColumns
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.mysql import (
    MySQLImplementation,
    _configured_schema,
    _connect_with_transient_retry,
)

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
    from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mysql import (
        MySQLSourceConfig,
    )

logger = structlog.get_logger(__name__)

# A binlog dump sends a large event only once the server has read it, so give a slow read room.
STREAM_READ_TIMEOUT_SECONDS = 300
_DUMP_EXCLUDED_KWARGS = ("database", "init_command")

_IDENTIFIER = r"`(?:[^`]|``)+`|[\w$]+"
_TRUNCATE = re.compile(rf"^TRUNCATE\s+(?:TABLE\s+)?(?P<name>{_IDENTIFIER})(?:\s*\.\s*(?P<table>{_IDENTIFIER}))?", re.I)
# Statements inside a transaction. MySQL writes each with its name or id, so they are matched by prefix.
_IN_TRANSACTION = ("BEGIN", "SAVEPOINT", "ROLLBACK TO", "RELEASE SAVEPOINT")


def _without_comments(query: str) -> str:
    """``query`` with its comments replaced by spaces, leaving quoted identifiers intact."""
    out: list[str] = []
    i = 0
    while i < len(query):
        char = query[i]
        if char == "`":
            end = i + 1
            while end < len(query):
                if query[end] == "`" and query[end + 1 : end + 2] != "`":
                    break
                end += 2 if query[end] == "`" else 1
            out.append(query[i : end + 1])
            i = end + 1
        elif query.startswith("/*", i):
            end = query.find("*/", i + 2)
            i = len(query) if end == -1 else end + 2
            out.append(" ")
        elif query.startswith("--", i) or char == "#":
            end = query.find("\n", i)
            i = len(query) if end == -1 else end
            out.append(" ")
        else:
            out.append(char)
            i += 1
    return "".join(out).strip()


def _unquote(identifier: str) -> str:
    return identifier[1:-1].replace("``", "`") if identifier.startswith("`") else identifier


def truncated_table(query: str, default_database: str) -> str | None:
    """The ``database.table`` a TRUNCATE statement empties, or None for any other statement."""
    match = _TRUNCATE.match(_without_comments(query))
    if match is None:
        return None
    if match.group("table") is not None:
        return f"{_unquote(match.group('name'))}.{_unquote(match.group('table'))}"
    return f"{default_database}.{_unquote(match.group('name'))}"


def server_time_zone(conn: pymysql.Connection) -> dt.tzinfo:
    """The zone a new session on the server reads TIMESTAMP columns in, which is the one a snapshot uses."""
    with conn.cursor() as cur:
        cur.execute("SELECT @@GLOBAL.time_zone, @@system_time_zone, TIMESTAMPDIFF(SECOND, UTC_TIMESTAMP(), NOW())")
        name, system_name, offset_seconds = cur.fetchone()
    name = system_name if str(name).upper() == "SYSTEM" else str(name)
    if str(name).upper() in ("UTC", "GMT", "+00:00"):
        return dt.UTC
    if offset := re.fullmatch(r"([+-])(\d{1,2}):(\d{2})", str(name)):
        sign = -1 if offset.group(1) == "-" else 1
        return dt.timezone(sign * dt.timedelta(hours=int(offset.group(2)), minutes=int(offset.group(3))))
    try:
        return zoneinfo.ZoneInfo(str(name))
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        # An abbreviation such as CEST names no zone, so the server's current offset stands in for it.
        return dt.timezone(dt.timedelta(seconds=int(offset_seconds)))


class MySQLCDCStreamReader:
    def __init__(
        self,
        source: ExternalDataSource,
        config: MySQLSourceConfig,
        cdc_config: MySQLCDCConfig,
        implementation: MySQLImplementation,
    ) -> None:
        self._source = source
        self._config = config
        self._cdc_config = cdc_config
        self._implementation = implementation
        self._position = BinlogPosition.deserialize(cdc_config.position) if cdc_config.position else None
        self._stack = ExitStack()
        self._kwargs: dict[str, Any] | None = None
        self._conn: pymysql.Connection | None = None
        self._buffer = TransactionBuffer()
        self._tables: dict[int, TableColumns] = {}
        self._key_columns: dict[str, list[str]] = {}
        self._key_change_columns: dict[str, frozenset[str]] = {}
        self._truncated: list[str] = []
        self._last_commit: BinlogPosition | None = None
        self._last_rows_consumed = 0
        self._time_zone: dt.tzinfo = dt.UTC

    def connect(self) -> None:
        if self._position is None or self._cdc_config.server_id is None:
            raise CDCStreamNotConfiguredError()
        kwargs = self._stack.enter_context(
            self._implementation.connection_kwargs(
                self._config, read_timeout=STREAM_READ_TIMEOUT_SECONDS, team_id=self._source.team_id
            )
        )
        self._kwargs = {key: value for key, value in kwargs.items() if key not in _DUMP_EXCLUDED_KWARGS}
        self._conn = self._open_connection(autocommit=True, read_timeout=MANAGEMENT_READ_TIMEOUT_SECONDS)
        binlog.require_readable(self._conn, self._position, self._cdc_config.server_uuid)
        self._time_zone = server_time_zone(self._conn)

    def _open_connection(self, **extra: Any) -> pymysql.Connection:
        assert self._kwargs is not None
        return _connect_with_transient_retry({**self._kwargs, **extra}, self._source.team_id)

    def _dump_connection(self, **settings: Any) -> pymysql.Connection:
        assert self._kwargs is not None
        # The library adds its own settings (a cursor class, a database for its control connection) on
        # top of the ones it was given, which already hold the tunnel endpoint and the TLS files.
        return self._open_connection(**{key: value for key, value in settings.items() if key not in self._kwargs})

    def read_changes(
        self, upto_nchanges: int | None = None, on_row: Callable[[], None] | None = None
    ) -> Iterator[ChangeEvent]:
        if self._conn is None or self._position is None or self._kwargs is None:
            raise RuntimeError("Not connected. Call connect() first.")
        start = self._position
        self._last_rows_consumed = 0
        self._buffer.discard()
        stream = BinLogStreamReader(
            connection_settings=dict(self._kwargs),
            server_id=self._cdc_config.server_id,
            log_file=start.file,
            log_pos=start.offset,
            resume_stream=True,
            blocking=False,
            only_events=[
                QueryEvent,
                XidEvent,
                WriteRowsEvent,
                UpdateRowsEvent,
                PartialUpdateRowsEvent,
                DeleteRowsEvent,
            ],
            # Rows of other databases are skipped before decoding, so their transactions cost nothing to buffer.
            only_schemas=[schema] if (schema := _configured_schema(self._config)) else None,
            pymysql_wrapper=self._dump_connection,
            enable_logging=False,
        )

        def position() -> BinlogPosition:
            return start.following(stream.log_file, stream.log_pos)

        try:
            for event in stream:
                if isinstance(event, PartialUpdateRowsEvent):
                    raise MySQLUnsupportedBinlogError(
                        f"A partial JSON update of {event.schema}.{event.table} carries only the changed paths. "
                        "Set binlog_row_value_options to an empty value."
                    )
                if isinstance(event, RowsEvent):
                    for change in self._changes(event):
                        self._last_rows_consumed += 1
                        if on_row is not None:
                            on_row()
                        self._buffer.add(change)
                    continue

                if isinstance(event, QueryEvent):
                    query = _without_comments(event.query)
                    statement = query.upper()
                    if statement.startswith(_IN_TRANSACTION):
                        continue
                    if statement.startswith("XA "):
                        # A prepared XA transaction commits later, after other transactions, which one read
                        # position can't hold.
                        raise MySQLUnsupportedBinlogError("XA transactions aren't supported by change data capture")
                    if statement != "COMMIT":
                        # Any other statement is DDL, which MySQL commits on its own.
                        table = truncated_table(query, _decode(event.schema))
                        if table is not None:
                            self._truncated.append(table)

                self._last_rows_consumed += 1
                if on_row is not None:
                    on_row()
                committed_at = dt.datetime.fromtimestamp(event.timestamp, tz=dt.UTC)
                commit = position()
                yield from self._buffer.commit(commit.serialize(), committed_at)
                self._last_commit = commit
                if upto_nchanges is not None and self._last_rows_consumed >= upto_nchanges:
                    return
        finally:
            # A read stopped mid-transaction leaves its changes unconfirmed, so the next read starts over.
            self._buffer.discard()
            stream.close()

    def _changes(self, event: RowsEvent) -> Iterator[ChangeEvent]:
        table_name = f"{event.schema}.{event.table}"
        columns = self._table_columns(event)
        self._key_columns[table_name] = columns.primary_key
        key_change_columns = self._key_change_columns.get(table_name)
        placeholder = dt.datetime.fromtimestamp(event.timestamp, tz=dt.UTC)
        for row in event.rows:
            if isinstance(event, UpdateRowsEvent):
                before = columns.normalize(row["before_values"], row["before_none_sources"], self._time_zone)
                after = columns.normalize(row["after_values"], row["after_none_sources"], self._time_zone)
                previous = None
                if key_change_columns and any(before.get(c) != after.get(c) for c in key_change_columns):
                    previous = {c: before.get(c) for c in key_change_columns}
                yield ChangeEvent(
                    operation="U",
                    table_name=table_name,
                    position_serialized="",
                    timestamp=placeholder,
                    columns=after,
                    column_types=columns.arrow_types,
                    previous_values=previous,
                )
            else:
                yield ChangeEvent(
                    operation="I" if isinstance(event, WriteRowsEvent) else "D",
                    table_name=table_name,
                    position_serialized="",
                    timestamp=placeholder,
                    columns=columns.normalize(row["values"], row["none_sources"], self._time_zone),
                    column_types=columns.arrow_types,
                )

    def _table_columns(self, event: RowsEvent) -> TableColumns:
        # The library keeps one column list per table map, and a schema change brings a new table map.
        cached = self._tables.get(event.table_id)
        if cached is None or cached.source is not event.columns:
            cached = TableColumns.from_binlog(event.columns, event.primary_key)
            self._tables[event.table_id] = cached
        return cached

    def confirm_position(self, position: str) -> None:
        """Store ``position`` on the source, so the next read and the next run start there."""
        target = BinlogPosition.deserialize(position)
        if self._position is not None and target < self._position:
            logger.info("binlog_position_already_ahead", position=position, stored=self._position.serialize())
            return
        self._position = self._store_position(target)
        logger.info("binlog_position_confirmed", position=self._position.serialize())

    def _store_position(self, position: BinlogPosition) -> BinlogPosition:
        """Store ``position`` unless the source already holds a later one, and return the position it holds.

        Another capture of the source, such as an attempt still running after its retry started, may have
        confirmed further already, and moving the stored position back would read its changes again."""
        from django.db import transaction

        from products.warehouse_sources.backend.logic.source_inputs import SourceInputsStore
        from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

        with transaction.atomic():
            # Locked and re-read, so a concurrent write of another `cdc_*` key survives this one.
            # The manager joins related rows, which Postgres can't lock on their nullable side.
            ExternalDataSource.objects.select_for_update(of=("self",)).filter(pk=self._source.pk).exists()
            self._source.refresh_from_db(fields=["job_inputs"])
            stored = MySQLCDCConfig.from_source(self._source).position
            if stored is not None and BinlogPosition.deserialize(stored) >= position:
                return BinlogPosition.deserialize(stored)
            SourceInputsStore.update_runtime(self._source, {POSITION_KEY: position.serialize()}, extra_update_fields=())
        return position

    def current_position(self) -> str | None:
        if self._conn is None or self._position is None:
            return None
        try:
            return binlog.visible_position(self._conn, self._position.epoch, self._position.base).serialize()
        except Exception:
            logger.warning("binlog_position_read_failed", exc_info=True)
            return None

    def get_primary_key_columns(self, schema_name: str, table_names: list[str]) -> dict[str, list[str]]:
        return {
            table: indexes["PRIMARY"]
            for table, indexes in self._query_index_columns(schema_name, table_names).items()
            if "PRIMARY" in indexes
        }

    def get_enforced_unique_keys(self, schema_name: str, table_names: list[str]) -> dict[str, list[frozenset[str]]]:
        return {
            table: [frozenset(columns) for columns in indexes.values()]
            for table, indexes in self._query_index_columns(schema_name, table_names).items()
        }

    def _query_index_columns(self, schema_name: str, table_names: list[str]) -> dict[str, dict[str, list[str]]]:
        """Per table, the columns of its primary key and of each unique index whose columns are all NOT NULL."""
        if self._conn is None:
            raise RuntimeError("Not connected. Call connect() first.")
        if not table_names:
            return {}
        placeholders = ", ".join(["%s"] * len(table_names))
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT s.TABLE_NAME, s.INDEX_NAME, s.COLUMN_NAME, c.IS_NULLABLE "
                "FROM information_schema.STATISTICS s JOIN information_schema.COLUMNS c "
                "ON c.TABLE_SCHEMA = s.TABLE_SCHEMA AND c.TABLE_NAME = s.TABLE_NAME AND c.COLUMN_NAME = s.COLUMN_NAME "
                f"WHERE s.TABLE_SCHEMA = %s AND s.TABLE_NAME IN ({placeholders}) AND s.NON_UNIQUE = 0 "
                "ORDER BY s.TABLE_NAME, s.INDEX_NAME, s.SEQ_IN_INDEX",
                [schema_name, *table_names],
            )
            rows = cur.fetchall()
        indexes: dict[str, dict[str, list[str]]] = {}
        nullable: set[str] = set()
        for table, index, column, is_nullable in rows:
            indexes.setdefault(str(table), {}).setdefault(str(index), []).append(str(column))
            if is_nullable == "YES":
                # Two rows may both hold NULL in a unique index, so it doesn't identify a row.
                nullable.add(f"{table}.{index}")
        return {
            table: {index: columns for index, columns in by_index.items() if f"{table}.{index}" not in nullable}
            for table, by_index in indexes.items()
        }

    def set_key_change_columns(self, columns_by_table: Mapping[str, Iterable[str]]) -> None:
        self._key_change_columns = {table: frozenset(columns) for table, columns in columns_by_table.items()}

    def get_decoder_key_columns(self, table_name: str) -> list[str]:
        return self._key_columns.get(table_name, [])

    @property
    def truncated_tables(self) -> list[str]:
        return list(self._truncated)

    def clear_truncated_tables(self) -> None:
        self._truncated = []

    @property
    def last_commit_position(self) -> str | None:
        return self._last_commit.serialize() if self._last_commit is not None else None

    @property
    def last_rows_consumed(self) -> int:
        return self._last_rows_consumed

    def close(self) -> None:
        self._buffer.discard()
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        self._stack.close()


def _decode(value: bytes | str | None) -> str:
    if isinstance(value, bytes):
        return value.decode()
    return value or ""
