"""Runs the CDC conformance suite over the Postgres adapter, reader and decoder.

The scripted database is rendered as pgoutput messages and served by a simulated replication slot,
so every change event comes out of the Postgres reader and decoder themselves. The connection, the
catalog key lookups and the slot DDL helpers are simulated. The connection answers the three
statements the reader sends.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from typing import Any

from unittest.mock import patch

import psycopg.errors

from products.warehouse_sources.backend.temporal.data_imports.cdc.adapters import CDCSourceAdapter
from products.warehouse_sources.backend.temporal.data_imports.cdc.tests.conformance_kit import (
    RowChange,
    SourceDatabase,
    TableDef,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.types import CDCConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter import PostgresCDCAdapter
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.decoder import _OID_INT8, _OID_TEXT
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.position import PgLSN
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.tests.test_decoder import (
    _make_begin,
    _make_commit,
    _make_delete,
    _make_insert,
    _make_relation,
    _make_truncate,
    _make_update,
)

_READER = "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.stream_reader"
_ADAPTER = "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter"

_SLOT_NAME = "posthog_slot"
# WAL bytes between two commits, so that transaction N ends at LSN N * _LSN_STEP.
_LSN_STEP = 0x100

_PEEK_LIMIT = re.compile(r"pg_logical_slot_peek_binary_changes\('[^']*', NULL, (\d+|NULL),")
_ADVANCE_TARGET = re.compile(r"pg_replication_slot_advance\('[^']*', '([^']+)'\)")

PeekRow = tuple[str, int, bytes]


def _lsn(transaction_number: int) -> str:
    return PgLSN(transaction_number * _LSN_STEP).serialize()


def _text(value: Any) -> tuple[str, str] | None:
    return None if value is None else ("t", str(value))


class _SimulatedSlot:
    def __init__(self, db: SourceDatabase) -> None:
        self._db = db
        self._relation_ids = {name: index + 1 for index, name in enumerate(db.tables)}

    def flush_lsn(self) -> str:
        return _lsn(self._db.head)

    def advance(self, lsn: str) -> None:
        target = PgLSN.deserialize(lsn).value // _LSN_STEP
        if target < self._db.confirmed:
            raise psycopg.errors.ObjectNotInPrerequisiteState(
                f"cannot advance replication slot to {lsn}, minimum is {_lsn(self._db.confirmed)}"
            )
        self._db.confirm(target)

    def peek(self, limit: int | None) -> Iterator[PeekRow]:
        if self._db.stream_lost:
            raise psycopg.errors.ObjectNotInPrerequisiteState(
                f'can no longer get changes from replication slot "{_SLOT_NAME}"'
            )
        # Postgres sends a relation once per decoding session, before the first change that uses it.
        announced: set[str] = set()
        emitted = 0
        for transaction in self._db.pending():
            end = transaction.number * _LSN_STEP
            commit = end - 0x10
            messages = [_make_begin(final_lsn=commit, timestamp=transaction.committed_at, xid=transaction.number)]
            for change in transaction.changes:
                table = self._db.tables[change.table]
                if change.table not in announced:
                    announced.add(change.table)
                    messages.append(self._relation(table))
                messages.append(self._change(table, change))
            messages.append(_make_commit(commit_lsn=commit, end_lsn=end, timestamp=transaction.committed_at))
            for message in messages:
                emitted += 1
                yield _lsn(transaction.number), transaction.number, message
            # A peek never splits a transaction, so the limit is checked after each commit.
            if limit is not None and emitted >= limit:
                return

    def _relation(self, table: TableDef) -> bytes:
        schema, name = table.name.split(".", 1)
        columns = [(column, _OID_INT8 if kind is int else _OID_TEXT, -1) for column, kind in table.columns.items()]
        return _make_relation(self._relation_ids[table.name], schema, name, columns, key_columns=set(table.primary_key))

    def _change(self, table: TableDef, change: RowChange) -> bytes:
        relation_id = self._relation_ids[table.name]
        if change.op == "T":
            return _make_truncate([relation_id])
        new = [_text(change.row.get(column)) for column in table.columns]
        if change.op == "I":
            return _make_insert(relation_id, new)
        assert change.old_row is not None
        # Under the default replica identity an old tuple holds the key, and NULL in every other column.
        old_key = [_text(change.old_row[column]) if column in table.primary_key else None for column in table.columns]
        if change.op == "D":
            return _make_delete(relation_id, old_key)
        # Postgres sends the old key of an update only when the update changed it.
        key_changed = table.key_of(change.old_row) != table.key_of(change.row)
        return _make_update(relation_id, new, old_values=old_key if key_changed else None)


class _SimulatedCursor:
    itersize = 0

    def __init__(self, slot: _SimulatedSlot) -> None:
        self._slot = slot
        self._rows: Iterator[tuple[Any, ...]] = iter(())

    def __enter__(self) -> _SimulatedCursor:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, query: Any) -> None:
        statement = query if isinstance(query, str) else query.as_string(None)
        if peek := _PEEK_LIMIT.search(statement):
            self._rows = self._slot.peek(None if peek.group(1) == "NULL" else int(peek.group(1)))
        elif advance := _ADVANCE_TARGET.search(statement):
            self._slot.advance(advance.group(1))
        elif "pg_current_wal_flush_lsn" in statement:
            self._rows = iter([(self._slot.flush_lsn(),)])
        else:
            raise AssertionError(f"The simulated slot does not answer this statement: {statement}")

    def fetchone(self) -> tuple[Any, ...] | None:
        return next(self._rows, None)

    def __iter__(self) -> Iterator[tuple[Any, ...]]:
        return self._rows


class _SimulatedConnection:
    def __init__(self, slot: _SimulatedSlot) -> None:
        self._slot = slot

    def cursor(self, name: str | None = None) -> _SimulatedCursor:
        return _SimulatedCursor(self._slot)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None


class SimulatedPostgres:
    source_type = "Postgres"

    def __init__(self, db: SourceDatabase) -> None:
        self._db = db
        self._slot = _SimulatedSlot(db)
        self.adapter: CDCSourceAdapter[CDCConfig] = PostgresCDCAdapter()

    def job_inputs(self) -> dict[str, Any]:
        return {
            "host": "db.example.com",
            "port": 5432,
            "database": "app",
            "user": "posthog",
            "password": "not-a-real-password",
            "schema": "public",
            "cdc_enabled": True,
            "cdc_slot_name": _SLOT_NAME,
            "cdc_publication_name": "posthog_pub",
        }

    @contextmanager
    def installed(self) -> Iterator[None]:
        with (
            patch(f"{_READER}._connect_to_postgres", side_effect=lambda **_: _SimulatedConnection(self._slot)),
            patch(f"{_READER}.get_primary_key_columns", side_effect=lambda _, *args: self._db.primary_keys(*args)),
            patch(f"{_READER}.get_enforced_unique_keys", side_effect=lambda _, *args: self._db.unique_keys(*args)),
            # Slot recreation runs DDL over a management connection, which the slot stands in for.
            patch(f"{_ADAPTER}.cdc_pg_connection", side_effect=lambda *_, **__: nullcontext()),
            patch(f"{_ADAPTER}.drop_slot"),
            patch(f"{_ADAPTER}.publication_exists", return_value=True),
            patch(f"{_ADAPTER}.create_slot", side_effect=lambda *_: _lsn(self._db.recreate_stream())),
        ):
            yield
