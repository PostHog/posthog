"""Runs the CDC conformance suite over the MySQL adapter and binlog reader.

The scripted database is rendered as the binlog events python-mysql-replication decodes, and served by a
simulated binlog dump, so every change event comes out of the MySQL reader itself. The server
connections, the catalog key lookups and the app-database write of a confirmed position are simulated.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from typing import Any

from unittest.mock import MagicMock, patch

import pymysql
from pymysqlreplication.column import Column
from pymysqlreplication.constants import FIELD_TYPE
from pymysqlreplication.event import QueryEvent, XidEvent
from pymysqlreplication.row_event import DeleteRowsEvent, UpdateRowsEvent, WriteRowsEvent

from products.warehouse_sources.backend.logic.source_inputs import SourceInputsStore
from products.warehouse_sources.backend.temporal.data_imports.cdc.adapters import CDCSourceAdapter
from products.warehouse_sources.backend.temporal.data_imports.cdc.tests.conformance_kit import (
    RowChange,
    SourceDatabase,
    TableDef,
    Transaction,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.types import CDCConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc import binlog
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.adapter import MySQLCDCAdapter
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.config import POSITION_KEY
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.position import BinlogPosition
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.stream_reader import (
    MySQLCDCStreamReader,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.mysql import MySQLImplementation

_READER = "products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.stream_reader"

_FILE = "binlog.000001"
_SERVER_UUID = "3e11fa47-71ca-11e1-9e33-c80aa9429562"
# Binlog bytes per transaction, so that transaction N ends at offset N * _STEP.
_STEP = 0x1000


def _end(transaction_number: int) -> int:
    return transaction_number * _STEP


def _event(kind: type, **attributes: Any) -> Any:
    # The library builds events from packets. These carry only what the reader reads.
    event = object.__new__(_FAKE_EVENTS[kind])
    event.__dict__.update(attributes)
    return event


class _Write(WriteRowsEvent):
    rows: list[dict[str, Any]] = []


class _Update(UpdateRowsEvent):
    rows: list[dict[str, Any]] = []


class _Delete(DeleteRowsEvent):
    rows: list[dict[str, Any]] = []


_FAKE_EVENTS: dict[type, type] = {
    WriteRowsEvent: _Write,
    UpdateRowsEvent: _Update,
    DeleteRowsEvent: _Delete,
    QueryEvent: QueryEvent,
    XidEvent: XidEvent,
}


class _SimulatedBinlog:
    def __init__(self, db: SourceDatabase) -> None:
        self._db = db
        self._table_ids = {name: index + 1 for index, name in enumerate(db.tables)}
        self._columns = {name: self._binlog_columns(table) for name, table in db.tables.items()}
        self.epoch = 0

    @staticmethod
    def _binlog_columns(table: TableDef) -> list[Column]:
        return [
            Column(
                type=FIELD_TYPE.LONGLONG if kind is int else FIELD_TYPE.VARCHAR,
                name=name,
                unsigned=False,
                character_set_name=None if kind is int else "utf8mb4",
            )
            for name, kind in table.columns.items()
        ]

    def position(self, epoch: int) -> BinlogPosition:
        return BinlogPosition.at(epoch, _FILE, _end(self._db.head) or 4)

    def events(self, stream: _SimulatedDump) -> Iterator[Any]:
        if self._db.stream_lost:
            raise pymysql.err.OperationalError(1236, "Could not find first log file name in binary log index file")
        for transaction in self._db.pending():
            if transaction.number <= stream.log_pos // _STEP:
                continue
            yield from self._render(transaction, stream)

    def _render(self, transaction: Transaction, stream: _SimulatedDump) -> Iterator[Any]:
        timestamp = int(transaction.committed_at.timestamp())
        start = _end(transaction.number - 1)
        rows = [change for change in transaction.changes if change.op != "T"]
        if rows:
            stream.log_pos = start + 1
            yield _event(QueryEvent, query="BEGIN", schema=b"", timestamp=timestamp)
            for index, change in enumerate(rows):
                stream.log_pos = start + 2 + index
                yield self._rows_event(change, timestamp)
        for change in transaction.changes:
            if change.op == "T":
                stream.log_pos = _end(transaction.number) - 1
                yield _event(QueryEvent, query=f"TRUNCATE TABLE {change.table}", schema=b"", timestamp=timestamp)
        stream.log_pos = _end(transaction.number)
        if rows:
            yield _event(XidEvent, timestamp=timestamp)

    def _rows_event(self, change: RowChange, timestamp: int) -> Any:
        table = self._db.tables[change.table]
        database, name = change.table.split(".", 1)
        if change.op == "U":
            assert change.old_row is not None
            kind, rows = UpdateRowsEvent, [{"before_values": dict(change.old_row), "after_values": dict(change.row)}]
        else:
            kind = WriteRowsEvent if change.op == "I" else DeleteRowsEvent
            rows = [{"values": dict(change.row)}]
        return _event(
            kind,
            schema=database,
            table=name,
            table_id=self._table_ids[change.table],
            columns=self._columns[change.table],
            primary_key=table.primary_key,
            timestamp=timestamp,
            rows=rows,
        )


class _SimulatedDump:
    """Stands in for `BinLogStreamReader`: a non-blocking dump from a position to the end of the log."""

    def __init__(self, server: _SimulatedBinlog, log_file: str, log_pos: int, **_: Any) -> None:
        self._server = server
        self.log_file = log_file
        self.log_pos = log_pos

    def __iter__(self) -> Iterator[Any]:
        return self._server.events(self)

    def close(self) -> None:
        return None


class SimulatedMySQL:
    source_type = "MySQL"

    def __init__(self, db: SourceDatabase) -> None:
        self._db = db
        self._server = _SimulatedBinlog(db)
        self.adapter: CDCSourceAdapter[CDCConfig] = MySQLCDCAdapter()

    def job_inputs(self) -> dict[str, Any]:
        return {
            "host": "db.example.com",
            "port": 3306,
            "database": "public",
            "user": "posthog",
            "password": "not-a-real-password",
            "schema": "public",
            "using_ssl": False,
            "cdc_enabled": True,
            "cdc_server_id": 424242,
            "cdc_server_uuid": _SERVER_UUID,
            POSITION_KEY: BinlogPosition.at(0, _FILE, 4).serialize(),
        }

    def _visible_position(self, _conn: Any, epoch: int) -> BinlogPosition:
        # Only stream recreation asks for a newer epoch than the one the server holds.
        if epoch > self._server.epoch:
            self._server.epoch = epoch
            self._db.recreate_stream()
        return self._server.position(epoch)

    def _require_readable(self, _conn: Any, _position: BinlogPosition, _server_uuid: str) -> None:
        if self._db.stream_lost:
            raise binlog.BinlogStreamLostError("The binlog file was purged before PostHog read it")

    def _store_position(self, reader: MySQLCDCStreamReader, position: BinlogPosition) -> None:
        self._db.confirm(position.offset // _STEP)
        SourceInputsStore.update_runtime(reader._source, {POSITION_KEY: position.serialize()})

    def _index_columns(
        self, _reader: MySQLCDCStreamReader, database: str, tables: list[str]
    ) -> dict[tuple[str, str], list[str]]:
        return {(table, "PRIMARY"): keys for table, keys in self._db.primary_keys(database, tables).items()}

    @contextmanager
    def installed(self) -> Iterator[None]:
        engine = self
        with (
            patch(f"{_READER}.BinLogStreamReader", side_effect=lambda **kwargs: _SimulatedDump(self._server, **kwargs)),
            patch(f"{_READER}._connect_with_transient_retry", return_value=MagicMock()),
            patch.object(MySQLImplementation, "connection_kwargs", lambda *_, **__: nullcontext({})),
            patch.object(MySQLImplementation, "connect", lambda *_, **__: nullcontext(MagicMock())),
            patch.object(binlog, "visible_position", self._visible_position),
            patch.object(binlog, "require_readable", self._require_readable),
            patch.object(binlog, "server_uuid", return_value=_SERVER_UUID),
            patch.object(
                MySQLCDCStreamReader,
                "_store_position",
                lambda reader, position: engine._store_position(reader, position),
            ),
            patch.object(
                MySQLCDCStreamReader,
                "_query_index_columns",
                lambda reader, database, tables: engine._index_columns(reader, database, tables),
            ),
        ):
            yield
