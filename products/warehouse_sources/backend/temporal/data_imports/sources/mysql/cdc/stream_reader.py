"""Reads row changes from a MySQL server's binary log, from the position PostHog holds.

Each read opens a non-blocking binlog dump at the confirmed position and stops at the end of the log.
Nothing on the server tracks what PostHog has read, so `confirm_position` stores the position on the
source, and a read that is not confirmed is read again by the next one, as a Postgres peek is.
"""

from __future__ import annotations

import re
import datetime as dt
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import ExitStack
from typing import TYPE_CHECKING, Any

import pymysql
import structlog
from pymysqlreplication import BinLogStreamReader
from pymysqlreplication.event import QueryEvent, XidEvent
from pymysqlreplication.row_event import DeleteRowsEvent, RowsEvent, UpdateRowsEvent, WriteRowsEvent

from products.warehouse_sources.backend.temporal.data_imports.cdc.errors import CDCStreamNotConfiguredError
from products.warehouse_sources.backend.temporal.data_imports.cdc.types import ChangeEvent
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc import binlog
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.config import (
    POSITION_KEY,
    MySQLCDCConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.position import BinlogPosition
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.transaction_buffer import (
    TransactionBuffer,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.values import TableColumns
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.mysql import (
    MySQLImplementation,
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

_TRUNCATE = re.compile(r"^\s*TRUNCATE\s+(?:TABLE\s+)?(?P<name>`[^`]+`|[\w$]+)(?:\.(?P<table>`[^`]+`|[\w$]+))?", re.I)
_TRANSACTION_CONTROL = frozenset({"BEGIN", "XA START", "SAVEPOINT"})


def _unquote(identifier: str) -> str:
    return identifier[1:-1].replace("``", "`") if identifier.startswith("`") else identifier


def truncated_table(query: str, default_database: str) -> str | None:
    """The ``database.table`` a TRUNCATE statement empties, or None for any other statement."""
    match = _TRUNCATE.match(query)
    if match is None:
        return None
    if match.group("table") is not None:
        return f"{_unquote(match.group('name'))}.{_unquote(match.group('table'))}"
    return f"{default_database}.{_unquote(match.group('name'))}"


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

    def connect(self) -> None:
        if self._position is None or self._cdc_config.server_id is None:
            raise CDCStreamNotConfiguredError()
        kwargs = self._stack.enter_context(
            self._implementation.connection_kwargs(
                self._config, read_timeout=STREAM_READ_TIMEOUT_SECONDS, team_id=self._source.team_id
            )
        )
        self._kwargs = {key: value for key, value in kwargs.items() if key not in _DUMP_EXCLUDED_KWARGS}
        self._conn = self._open_connection(autocommit=True)
        binlog.require_readable(self._conn, self._position, self._cdc_config.server_uuid)

    def _open_connection(self, **extra: Any) -> pymysql.Connection:
        assert self._kwargs is not None
        return _connect_with_transient_retry({**self._kwargs, **extra}, self._source.team_id)

    def _dump_connection(self, **settings: Any) -> pymysql.Connection:
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
            only_events=[QueryEvent, XidEvent, WriteRowsEvent, UpdateRowsEvent, DeleteRowsEvent],
            pymysql_wrapper=self._dump_connection,
            enable_logging=False,
        )

        def position() -> BinlogPosition:
            return BinlogPosition.at(start.epoch, stream.log_file, stream.log_pos)

        try:
            for event in stream:
                if isinstance(event, RowsEvent):
                    for change in self._changes(event):
                        self._last_rows_consumed += 1
                        if on_row is not None:
                            on_row()
                        self._buffer.add(change)
                    continue

                if isinstance(event, QueryEvent):
                    query = event.query.strip()
                    if query.upper() in _TRANSACTION_CONTROL:
                        continue
                    if query.upper() != "COMMIT":
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
                before = columns.normalize(row["before_values"])
                after = columns.normalize(row["after_values"])
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
                    columns=columns.normalize(row["values"]),
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
        self._store_position(target)
        self._position = target
        logger.info("binlog_position_confirmed", position=position)

    def _store_position(self, position: BinlogPosition) -> None:
        from django.db import transaction

        from products.warehouse_sources.backend.logic.source_inputs import SourceInputsStore
        from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

        with transaction.atomic():
            # Locked and re-read, so a concurrent write of another `cdc_*` key survives this one.
            # The manager joins related rows, which Postgres can't lock on their nullable side.
            locked = ExternalDataSource.objects.select_for_update(of=("self",)).get(pk=self._source.pk)
            self._source.job_inputs = locked.job_inputs
            SourceInputsStore.update_runtime(self._source, {POSITION_KEY: position.serialize()}, extra_update_fields=())

    def current_position(self) -> str | None:
        if self._conn is None or self._position is None:
            return None
        try:
            return binlog.visible_position(self._conn, self._position.epoch).serialize()
        except Exception:
            logger.warning("binlog_position_read_failed", exc_info=True)
            return None

    def get_primary_key_columns(self, schema_name: str, table_names: list[str]) -> dict[str, list[str]]:
        return {
            table: columns
            for (table, index), columns in self._query_index_columns(schema_name, table_names).items()
            if index == "PRIMARY"
        }

    def get_enforced_unique_keys(self, schema_name: str, table_names: list[str]) -> dict[str, list[frozenset[str]]]:
        keys: dict[str, list[frozenset[str]]] = {}
        for (table, _), columns in self._query_index_columns(schema_name, table_names).items():
            keys.setdefault(table, []).append(frozenset(columns))
        return keys

    def _query_index_columns(self, schema_name: str, table_names: list[str]) -> dict[tuple[str, str], list[str]]:
        """Columns of every primary key and unique index whose columns are all NOT NULL, in index order."""
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
        indexes: dict[tuple[str, str], list[str]] = {}
        nullable: set[tuple[str, str]] = set()
        for table, index, column, is_nullable in rows:
            indexes.setdefault((str(table), str(index)), []).append(str(column))
            if is_nullable == "YES":
                # Two rows may both hold NULL in a unique index, so it doesn't identify a row.
                nullable.add((str(table), str(index)))
        return {key: columns for key, columns in indexes.items() if key not in nullable}

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
