import io
import struct
from datetime import UTC, datetime

import pytest
from unittest.mock import MagicMock, patch

import pyarrow as pa
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.cdc.errors import CDCTransactionTooLargeError
from products.warehouse_sources.backend.temporal.data_imports.cdc.types import ChangeEvent
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.decoder import (
    _OID_BOOL,
    _OID_FLOAT8,
    _OID_INT4,
    _OID_INT8,
    _OID_JSONB,
    _OID_TEXT,
    PG_EPOCH_OFFSET_US,
    CDCSpillBudgetExhaustedError,
    PgOutputDecoder,
    Relation,
    RelationColumn,
    _pg_timestamp_to_datetime,
    _WorkerSpillBudget,
)

_DECODER_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.decoder"


def _make_cstring(s: str) -> bytes:
    return s.encode("utf-8") + b"\x00"


def _make_lsn(value: int) -> bytes:
    return struct.pack("!Q", value)


def _make_pg_timestamp(dt: datetime) -> bytes:
    unix_us = int(dt.timestamp() * 1_000_000)
    pg_us = unix_us - PG_EPOCH_OFFSET_US
    return struct.pack("!q", pg_us)


def _make_begin(final_lsn: int = 0x100, timestamp: datetime | None = None, xid: int = 1) -> bytes:
    if timestamp is None:
        timestamp = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)
    return b"B" + _make_lsn(final_lsn) + _make_pg_timestamp(timestamp) + struct.pack("!I", xid)


def _make_commit(
    flags: int = 0, commit_lsn: int = 0x100, end_lsn: int = 0x200, timestamp: datetime | None = None
) -> bytes:
    if timestamp is None:
        timestamp = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)
    return b"C" + struct.pack("!B", flags) + _make_lsn(commit_lsn) + _make_lsn(end_lsn) + _make_pg_timestamp(timestamp)


def _make_relation(
    relation_id: int,
    schema: str,
    table: str,
    columns: list[tuple[str, int, int]],
    replica_identity: int = 0,
) -> bytes:
    """Build a Relation (R) message.

    columns: list of (name, type_oid, type_modifier) tuples.
    """
    data = b"R"
    data += struct.pack("!I", relation_id)
    data += _make_cstring(schema)
    data += _make_cstring(table)
    data += struct.pack("!B", replica_identity)
    data += struct.pack("!H", len(columns))

    for col_name, type_oid, type_mod in columns:
        flags = 1  # part of key by default
        data += struct.pack("!B", flags)
        data += _make_cstring(col_name)
        data += struct.pack("!I", type_oid)
        data += struct.pack("!i", type_mod)

    return data


def _make_tuple_data(values: list[tuple[str, str] | None]) -> bytes:
    """Build tuple data: n_cols(2) + per-column data.

    values: list of (type_char, text_value) or None for null.
      type_char: 'n' for null, 't' for text value, 'u' for unchanged TOAST
    """
    data = struct.pack("!H", len(values))
    for val in values:
        if val is None:
            data += b"n"
        elif val[0] == "u":
            data += b"u"
        else:
            text_bytes = val[1].encode("utf-8")
            data += b"t" + struct.pack("!I", len(text_bytes)) + text_bytes
    return data


def _make_insert(relation_id: int, values: list[tuple[str, str] | None]) -> bytes:
    return b"I" + struct.pack("!I", relation_id) + b"N" + _make_tuple_data(values)


def _make_update(
    relation_id: int,
    new_values: list[tuple[str, str] | None],
    old_values: list[tuple[str, str] | None] | None = None,
    old_marker: bytes = b"K",
) -> bytes:
    data = b"U" + struct.pack("!I", relation_id)
    if old_values is not None:
        data += old_marker + _make_tuple_data(old_values)
    data += b"N" + _make_tuple_data(new_values)
    return data


def _make_delete(relation_id: int, key_values: list[tuple[str, str] | None]) -> bytes:
    return b"D" + struct.pack("!I", relation_id) + b"K" + _make_tuple_data(key_values)


def _make_truncate(relation_ids: list[int], flags: int = 0) -> bytes:
    data = b"T" + struct.pack("!I", len(relation_ids)) + struct.pack("!B", flags)
    for rid in relation_ids:
        data += struct.pack("!I", rid)
    return data


class TestPgOutputDecoder:
    """Tests for the pgoutput binary protocol decoder."""

    def _setup_decoder_with_relation(
        self,
        relation_id: int = 1,
        table: str = "users",
        columns: list[tuple[str, int, int]] | None = None,
    ) -> PgOutputDecoder:
        if columns is None:
            columns = [("id", _OID_INT4, -1), ("name", _OID_TEXT, -1), ("email", _OID_TEXT, -1)]

        decoder = PgOutputDecoder()
        relation_msg = _make_relation(relation_id, "public", table, columns)
        decoder.decode_message(relation_msg, "0/100")
        return decoder

    def test_begin_commit_empty_transaction(self):
        decoder = PgOutputDecoder()
        begin = _make_begin()
        commit = _make_commit()

        events = list(decoder.decode_message(begin, "0/100"))
        assert events == []

        events = list(decoder.decode_message(commit, "0/200"))
        assert events == []

    def test_event_table_name_is_schema_qualified(self):
        # ChangeEvent.table_name must be `schema.table` to match the qualified
        # ExternalDataSchema.name the CDC extraction activity filters on. A bare table
        # name silently drops every change for multi-schema-era (qualified) schemas.
        decoder = self._setup_decoder_with_relation(
            relation_id=7, table="cdc_test_orders", columns=[("id", _OID_INT4, -1)]
        )
        decoder.decode_message(_make_begin(), "0/100")
        decoder.decode_message(_make_insert(7, [("t", "1")]), "0/150")
        events = list(decoder.decode_message(_make_commit(), "0/200"))

        assert len(events) == 1
        assert events[0].table_name == "public.cdc_test_orders"

    def test_insert_event(self):
        decoder = self._setup_decoder_with_relation(columns=[("id", _OID_INT4, -1), ("name", _OID_TEXT, -1)])

        begin = _make_begin()
        insert = _make_insert(1, [("t", "42"), ("t", "Alice")])
        commit = _make_commit()

        decoder.decode_message(begin, "0/100")
        decoder.decode_message(insert, "0/150")
        events = list(decoder.decode_message(commit, "0/200"))

        assert len(events) == 1
        event = events[0]
        assert event.operation == "I"
        assert event.table_name == "public.users"
        assert event.columns["id"] == 42
        assert event.columns["name"] == "Alice"

    def test_update_event(self):
        decoder = self._setup_decoder_with_relation(columns=[("id", _OID_INT4, -1), ("name", _OID_TEXT, -1)])

        begin = _make_begin()
        update = _make_update(1, [("t", "42"), ("t", "Bob")])
        commit = _make_commit()

        decoder.decode_message(begin, "0/100")
        decoder.decode_message(update, "0/150")
        events = list(decoder.decode_message(commit, "0/200"))

        assert len(events) == 1
        event = events[0]
        assert event.operation == "U"
        assert event.table_name == "public.users"
        assert event.columns["id"] == 42
        assert event.columns["name"] == "Bob"

    def test_update_with_old_key(self):
        decoder = self._setup_decoder_with_relation(columns=[("id", _OID_INT4, -1), ("name", _OID_TEXT, -1)])

        begin = _make_begin()
        update = _make_update(
            1,
            new_values=[("t", "42"), ("t", "Bob")],
            old_values=[("t", "42"), ("t", "Alice")],
        )
        commit = _make_commit()

        decoder.decode_message(begin, "0/100")
        decoder.decode_message(update, "0/150")
        events = list(decoder.decode_message(commit, "0/200"))

        assert len(events) == 1
        assert events[0].operation == "U"
        assert events[0].columns["name"] == "Bob"

    def test_delete_event(self):
        decoder = self._setup_decoder_with_relation(columns=[("id", _OID_INT4, -1), ("name", _OID_TEXT, -1)])

        begin = _make_begin()
        delete = _make_delete(1, [("t", "42"), None])
        commit = _make_commit()

        decoder.decode_message(begin, "0/100")
        decoder.decode_message(delete, "0/150")
        events = list(decoder.decode_message(commit, "0/200"))

        assert len(events) == 1
        event = events[0]
        assert event.operation == "D"
        assert event.table_name == "public.users"
        assert event.columns["id"] == 42
        assert event.columns.get("name") is None

    def test_null_values(self):
        decoder = self._setup_decoder_with_relation(
            columns=[("id", _OID_INT4, -1), ("name", _OID_TEXT, -1), ("email", _OID_TEXT, -1)]
        )

        begin = _make_begin()
        insert = _make_insert(1, [("t", "1"), None, ("t", "test@example.com")])
        commit = _make_commit()

        decoder.decode_message(begin, "0/100")
        decoder.decode_message(insert, "0/150")
        events = list(decoder.decode_message(commit, "0/200"))

        assert len(events) == 1
        assert events[0].columns["id"] == 1
        assert events[0].columns["name"] is None
        assert events[0].columns["email"] == "test@example.com"

    def test_event_carries_column_arrow_types(self):
        # Events expose the Arrow type per column from the relation OIDs, so the batcher
        # can type a column the same way even in a micro-batch where it's all-null.
        decoder = self._setup_decoder_with_relation(
            columns=[
                ("id", _OID_INT8, -1),
                ("seats", _OID_INT4, -1),
                ("price", _OID_FLOAT8, -1),
                ("active", _OID_BOOL, -1),
                ("payload", _OID_JSONB, -1),
                ("name", _OID_TEXT, -1),
            ]
        )

        decoder.decode_message(_make_begin(), "0/100")
        decoder.decode_message(
            _make_insert(1, [("t", "1"), ("t", "5"), ("t", "9.5"), ("t", "t"), ("t", "{}"), ("t", "x")]), "0/150"
        )
        events = list(decoder.decode_message(_make_commit(), "0/200"))

        assert events[0].column_types == {
            "id": pa.int64(),
            "seats": pa.int64(),
            "price": pa.float64(),
            "active": pa.bool_(),
            "payload": pa.string(),
            "name": pa.string(),
        }

    def test_unchanged_toast_column(self):
        decoder = self._setup_decoder_with_relation(columns=[("id", _OID_INT4, -1), ("big_text", _OID_TEXT, -1)])

        begin = _make_begin()
        # Update where big_text is unchanged TOAST
        update = _make_update(1, [("t", "1"), ("u", "")])
        commit = _make_commit()

        decoder.decode_message(begin, "0/100")
        decoder.decode_message(update, "0/150")
        events = list(decoder.decode_message(commit, "0/200"))

        assert len(events) == 1
        assert events[0].columns["id"] == 1
        # Not in columns (no value was sent), but marked omitted so downstream
        # fills it from the last known state instead of writing NULL over it.
        assert "big_text" not in events[0].columns
        assert events[0].omitted_columns == frozenset({"big_text"})

    def test_unchanged_toast_filled_from_replica_identity_full_old_tuple(self):
        # With REPLICA IDENTITY FULL the old tuple carries the TOAST value; since the
        # column is unchanged, the old value IS the current value — no marker needed.
        decoder = self._setup_decoder_with_relation(columns=[("id", _OID_INT4, -1), ("big_text", _OID_TEXT, -1)])

        decoder.decode_message(_make_begin(), "0/100")
        update = _make_update(
            1,
            new_values=[("t", "1"), ("u", "")],
            old_values=[("t", "1"), ("t", "big toasted value")],
            old_marker=b"O",
        )
        decoder.decode_message(update, "0/150")
        events = list(decoder.decode_message(_make_commit(), "0/200"))

        assert len(events) == 1
        assert events[0].columns["big_text"] == "big toasted value"
        assert events[0].omitted_columns == frozenset()

    def test_transaction_buffering(self):
        decoder = self._setup_decoder_with_relation(columns=[("id", _OID_INT4, -1)])

        begin = _make_begin()
        insert1 = _make_insert(1, [("t", "1")])
        insert2 = _make_insert(1, [("t", "2")])
        insert3 = _make_insert(1, [("t", "3")])

        # Events should NOT be returned until Commit
        assert list(decoder.decode_message(begin, "0/100")) == []
        assert list(decoder.decode_message(insert1, "0/110")) == []
        assert list(decoder.decode_message(insert2, "0/120")) == []
        assert list(decoder.decode_message(insert3, "0/130")) == []

        commit = _make_commit()
        events = list(decoder.decode_message(commit, "0/200"))

        assert len(events) == 3
        assert [e.columns["id"] for e in events] == [1, 2, 3]

    def test_multiple_transactions(self):
        decoder = self._setup_decoder_with_relation(columns=[("id", _OID_INT4, -1)])

        # Transaction 1
        decoder.decode_message(_make_begin(), "0/100")
        decoder.decode_message(_make_insert(1, [("t", "1")]), "0/110")
        events1 = list(decoder.decode_message(_make_commit(), "0/200"))

        # Transaction 2
        decoder.decode_message(_make_begin(), "0/300")
        decoder.decode_message(_make_insert(1, [("t", "2")]), "0/310")
        events2 = list(decoder.decode_message(_make_commit(), "0/400"))

        assert len(events1) == 1
        assert events1[0].columns["id"] == 1
        assert len(events2) == 1
        assert events2[0].columns["id"] == 2

    def test_multi_column_primary_key(self):
        decoder = self._setup_decoder_with_relation(
            columns=[
                ("tenant_id", _OID_INT4, -1),
                ("user_id", _OID_INT4, -1),
                ("score", _OID_FLOAT8, -1),
            ]
        )

        decoder.decode_message(_make_begin(), "0/100")
        decoder.decode_message(
            _make_insert(1, [("t", "10"), ("t", "20"), ("t", "99.5")]),
            "0/110",
        )
        events = list(decoder.decode_message(_make_commit(), "0/200"))

        assert len(events) == 1
        assert events[0].columns["tenant_id"] == 10
        assert events[0].columns["user_id"] == 20
        assert events[0].columns["score"] == 99.5

    def test_utf8_multibyte_strings(self):
        decoder = self._setup_decoder_with_relation(columns=[("id", _OID_INT4, -1), ("name", _OID_TEXT, -1)])

        decoder.decode_message(_make_begin(), "0/100")
        decoder.decode_message(
            _make_insert(1, [("t", "1"), ("t", "日本語テスト 🎉")]),
            "0/110",
        )
        events = list(decoder.decode_message(_make_commit(), "0/200"))

        assert len(events) == 1
        assert events[0].columns["name"] == "日本語テスト 🎉"

    def test_relation_cache_update(self):
        decoder = PgOutputDecoder()

        # Initial schema: id, name
        rel1 = _make_relation(1, "public", "users", [("id", _OID_INT4, -1), ("name", _OID_TEXT, -1)])
        decoder.decode_message(rel1, "0/50")

        decoder.decode_message(_make_begin(), "0/100")
        decoder.decode_message(_make_insert(1, [("t", "1"), ("t", "Alice"), None]), "0/110")
        events1 = list(decoder.decode_message(_make_commit(), "0/200"))

        assert events1[0].columns == {"id": 1, "name": "Alice"}

        # Schema change: id, name, email (new column)
        rel2 = _make_relation(
            1, "public", "users", [("id", _OID_INT4, -1), ("name", _OID_TEXT, -1), ("email", _OID_TEXT, -1)]
        )
        decoder.decode_message(rel2, "0/250")

        decoder.decode_message(_make_begin(), "0/300")
        decoder.decode_message(
            _make_insert(1, [("t", "2"), ("t", "Bob"), ("t", "bob@example.com")]),
            "0/310",
        )
        events2 = list(decoder.decode_message(_make_commit(), "0/400"))

        assert events2[0].columns == {"id": 2, "name": "Bob", "email": "bob@example.com"}

    @parameterized.expand([("in_memory", 100), ("spilled", 1)])
    def test_a_truncate_shows_only_once_its_transactions_changes_are_consumed(self, _name, chunk):
        with patch(f"{_DECODER_MODULE}.TX_SPILL_CHUNK_EVENTS", chunk):
            decoder = self._setup_decoder_with_relation(relation_id=1, table="users")
            decoder.decode_message(_make_begin(), "0/100")
            decoder.decode_message(_make_insert(1, [("t", "1"), ("t", "Alice"), None]), "0/110")
            decoder.decode_message(_make_insert(1, [("t", "2"), ("t", "Bob"), None]), "0/120")
            decoder.decode_message(_make_truncate([1]), "0/130")
            events = iter(decoder.decode_message(_make_commit(), "0/200"))

            next(events)
            assert decoder.truncated_tables == []
            assert len(list(events)) == 1
            assert decoder.truncated_tables == ["public.users"]

        decoder.clear_truncated_tables()
        assert decoder.truncated_tables == []

    def test_multiple_tables(self):
        decoder = PgOutputDecoder()

        rel1 = _make_relation(1, "public", "users", [("id", _OID_INT4, -1)])
        rel2 = _make_relation(2, "public", "orders", [("id", _OID_INT4, -1), ("user_id", _OID_INT4, -1)])
        decoder.decode_message(rel1, "0/50")
        decoder.decode_message(rel2, "0/60")

        decoder.decode_message(_make_begin(), "0/100")
        decoder.decode_message(_make_insert(1, [("t", "1")]), "0/110")
        decoder.decode_message(_make_insert(2, [("t", "100"), ("t", "1")]), "0/120")
        events = list(decoder.decode_message(_make_commit(), "0/200"))

        assert len(events) == 2
        assert events[0].table_name == "public.users"
        assert events[0].columns["id"] == 1
        assert events[1].table_name == "public.orders"
        assert events[1].columns["id"] == 100
        assert events[1].columns["user_id"] == 1

    @parameterized.expand(
        [
            ("bool_true", _OID_BOOL, "t", True),
            ("bool_false", _OID_BOOL, "f", False),
            ("int4", _OID_INT4, "42", 42),
            ("int8", _OID_INT8, "9999999999", 9999999999),
            ("float8", _OID_FLOAT8, "3.14", 3.14),
            ("jsonb", _OID_JSONB, '{"key": "value"}', '{"key": "value"}'),
        ]
    )
    def test_type_casting(self, _name, type_oid, text_value, expected):
        decoder = self._setup_decoder_with_relation(columns=[("val", type_oid, -1)])

        decoder.decode_message(_make_begin(), "0/100")
        decoder.decode_message(_make_insert(1, [("t", text_value)]), "0/110")
        events = list(decoder.decode_message(_make_commit(), "0/200"))

        assert events[0].columns["val"] == expected

    def test_unknown_relation_id_skipped(self):
        decoder = PgOutputDecoder()
        # No relation registered for id 99

        decoder.decode_message(_make_begin(), "0/100")
        decoder.decode_message(_make_insert(99, [("t", "1")]), "0/110")
        events = list(decoder.decode_message(_make_commit(), "0/200"))

        assert len(events) == 0

    def test_empty_message(self):
        decoder = PgOutputDecoder()
        events = list(decoder.decode_message(b"", "0/100"))
        assert events == []

    def test_unknown_message_type_ignored(self):
        decoder = PgOutputDecoder()
        events = list(decoder.decode_message(b"Z\x00\x00", "0/100"))
        assert events == []

    def test_mixed_operations_in_transaction(self):
        decoder = self._setup_decoder_with_relation(columns=[("id", _OID_INT4, -1), ("name", _OID_TEXT, -1)])

        decoder.decode_message(_make_begin(), "0/100")
        decoder.decode_message(_make_insert(1, [("t", "1"), ("t", "Alice"), None]), "0/110")
        decoder.decode_message(_make_update(1, [("t", "1"), ("t", "Alice Updated")]), "0/120")
        decoder.decode_message(_make_delete(1, [("t", "2"), None]), "0/130")
        events = list(decoder.decode_message(_make_commit(), "0/200"))

        assert len(events) == 3
        assert events[0].operation == "I"
        assert events[1].operation == "U"
        assert events[1].columns["name"] == "Alice Updated"
        assert events[2].operation == "D"
        assert events[2].columns["id"] == 2


class TestPgTimestamp:
    def test_pg_timestamp_to_datetime(self):
        dt = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)
        unix_us = int(dt.timestamp() * 1_000_000)
        pg_us = unix_us - PG_EPOCH_OFFSET_US
        result = _pg_timestamp_to_datetime(pg_us)
        assert result == dt

    def test_pg_epoch(self):
        result = _pg_timestamp_to_datetime(0)
        assert result == datetime(2000, 1, 1, tzinfo=UTC)


class TestTransactionBufferGuard:
    _COLUMNS = [("id", _OID_INT4, -1), ("name", _OID_TEXT, -1), ("active", _OID_BOOL, -1), ("score", _OID_FLOAT8, -1)]

    def _decoder_with_relation(self) -> PgOutputDecoder:
        decoder = PgOutputDecoder()
        decoder.decode_message(_make_relation(1, "public", "users", self._COLUMNS), "0/1")
        return decoder

    def _row(self, i: int) -> list[tuple[str, str] | None]:
        return [("t", str(i)), None if i % 2 else ("t", f"用户 {i}"), ("t", "t"), ("t", f"{i}.5")]

    def _decode(self, decoder: PgOutputDecoder, messages: list[bytes]) -> list[ChangeEvent]:
        decoder.decode_message(_make_begin(), "0/1")
        for message in messages:
            assert list(decoder.decode_message(message, "0/1")) == []
        return list(decoder.decode_message(_make_commit(end_lsn=0x500), "0/2"))

    def _mixed_transaction(self) -> list[bytes]:
        retyped = [("id", _OID_INT4, -1), ("name", _OID_TEXT, -1), ("active", _OID_BOOL, -1), ("score", _OID_TEXT, -1)]
        return [
            *(_make_insert(1, self._row(i)) for i in range(4)),
            _make_update(1, [("t", "2"), ("u", ""), ("t", "f"), ("t", "9.5")]),
            _make_relation(1, "public", "users", retyped),
            *(_make_insert(1, self._row(i)) for i in range(4, 7)),
        ]

    @parameterized.expand([("spills_whole_chunks", 4), ("spills_with_a_tail", 3)])
    def test_a_spilled_transaction_comes_back_identical_at_the_commit_position(self, _name: str, chunk: int) -> None:
        with patch(f"{_DECODER_MODULE}.TX_SPILL_CHUNK_EVENTS", 100):
            in_memory = self._decode(self._decoder_with_relation(), self._mixed_transaction())
        with patch(f"{_DECODER_MODULE}.TX_SPILL_CHUNK_EVENTS", chunk):
            decoder = self._decoder_with_relation()
            spilled = self._decode(decoder, self._mixed_transaction())
            follow_up = self._decode(decoder, [_make_insert(1, self._row(100))])

        assert spilled == in_memory
        assert {e.position_serialized for e in spilled} == {"0/500"}
        assert spilled[4].omitted_columns == frozenset({"name"})
        assert spilled[0].column_types != spilled[-1].column_types
        assert [e.columns["id"] for e in follow_up] == [100]

    @parameterized.expand(
        [
            ("change_count", "MAX_TX_BUFFER_EVENTS", 3),
            ("spill_bytes", "MAX_TX_SPILL_BYTES", 1),
            ("larger_than_the_worker_budget", "_worker_spill_budget", _WorkerSpillBudget(limit=1)),
        ]
    )
    def test_raises_when_transaction_exceeds_a_cap(self, _name: str, cap: str, value: object) -> None:
        with patch(f"{_DECODER_MODULE}.{cap}", value), patch(f"{_DECODER_MODULE}.TX_SPILL_CHUNK_EVENTS", 4):
            decoder = self._decoder_with_relation()
            decoder.decode_message(_make_begin(), "0/1")
            for i in range(3):
                decoder.decode_message(_make_insert(1, [("t", str(i)), None, None, None]), "0/1")

            with pytest.raises(CDCTransactionTooLargeError):
                decoder.decode_message(_make_insert(1, [("t", "99"), None, None, None]), "0/1")

    def test_concurrent_transactions_share_the_worker_spill_budget(self) -> None:
        row = _make_insert(1, [("t", "1"), None, None, None])
        with patch(f"{_DECODER_MODULE}.TX_SPILL_CHUNK_EVENTS", 1):
            probe = io.BytesIO()
            with patch(f"{_DECODER_MODULE}.tempfile.TemporaryFile", return_value=probe):
                measured = self._decoder_with_relation()
                measured.decode_message(_make_begin(), "0/1")
                measured.decode_message(row, "0/1")
                line = len(probe.getvalue())
                measured.close()

            with patch(f"{_DECODER_MODULE}._worker_spill_budget", _WorkerSpillBudget(limit=line * 5 // 2)):
                first, second = self._decoder_with_relation(), self._decoder_with_relation()
                first.decode_message(_make_begin(), "0/1")
                first.decode_message(row, "0/1")
                first.decode_message(row, "0/1")
                second.decode_message(_make_begin(), "0/1")

                with pytest.raises(CDCSpillBudgetExhaustedError):
                    second.decode_message(row, "0/1")

                assert len(list(first.decode_message(_make_commit(), "0/2"))) == 2
                assert len(self._decode(second, [row, row])) == 2

    def test_a_failed_spill_write_returns_its_budget_on_close(self) -> None:
        budget = _WorkerSpillBudget(limit=10_000)
        full_disk = MagicMock()
        full_disk.write.side_effect = OSError(28, "No space left on device")
        with (
            patch(f"{_DECODER_MODULE}.TX_SPILL_CHUNK_EVENTS", 1),
            patch(f"{_DECODER_MODULE}._worker_spill_budget", budget),
            patch(f"{_DECODER_MODULE}.tempfile.TemporaryFile", return_value=full_disk),
        ):
            decoder = self._decoder_with_relation()
            decoder.decode_message(_make_begin(), "0/1")
            with pytest.raises(OSError):
                decoder.decode_message(_make_insert(1, [("t", "1"), None, None, None]), "0/1")

            decoder.close()

        assert budget.reserve(10_000)

    @parameterized.expand([("at_a_spill", 1), ("at_commit", 100)])
    def test_raises_when_decoding_a_transaction_outlasts_the_time_limit(self, _name: str, chunk: int) -> None:
        clock = iter([0.0, 3601.0])
        with (
            patch(f"{_DECODER_MODULE}.TX_SPILL_CHUNK_EVENTS", chunk),
            patch(f"{_DECODER_MODULE}.time.monotonic", side_effect=lambda: next(clock)),
        ):
            decoder = self._decoder_with_relation()
            decoder.decode_message(_make_begin(), "0/1")

            with pytest.raises(CDCTransactionTooLargeError):
                decoder.decode_message(_make_insert(1, [("t", "1"), None, None, None]), "0/1")
                decoder.decode_message(_make_commit(), "0/2")

    @parameterized.expand([("before_commit", False), ("mid_replay", True)])
    def test_close_releases_the_spill(self, _name: str, committed: bool) -> None:
        spill = io.BytesIO()
        with (
            patch(f"{_DECODER_MODULE}.TX_SPILL_CHUNK_EVENTS", 1),
            patch(f"{_DECODER_MODULE}.tempfile.TemporaryFile", return_value=spill),
        ):
            decoder = self._decoder_with_relation()
            decoder.decode_message(_make_begin(), "0/1")
            decoder.decode_message(_make_insert(1, [("t", "1"), None, None, None]), "0/1")
            decoder.decode_message(_make_insert(1, [("t", "2"), None, None, None]), "0/1")
            if committed:
                replay = iter(decoder.decode_message(_make_commit(), "0/2"))
                next(replay)
                assert not spill.closed

            decoder.close()

        assert spill.closed


class TestReplicaIdentityKeyColumns:
    def _decoder_with(self, replica_identity: int = 0, key_flags: tuple[int, ...] = (1, 0, 0)) -> PgOutputDecoder:
        decoder = PgOutputDecoder()
        decoder._relations[1] = Relation(
            relation_id=1,
            schema_name="cdc_test",
            table_name="orders",
            replica_identity=replica_identity,
            columns=[
                RelationColumn(flags=flags, name=name, type_oid=_OID_INT8, type_modifier=-1)
                for flags, name in zip(key_flags, ["id", "tenant_id", "total"])
            ],
        )
        return decoder

    @parameterized.expand(
        [
            ("qualified", "cdc_test.orders", ["id"]),
            ("bare", "orders", ["id"]),
            ("other_schema", "public.orders", []),
        ]
    )
    def test_lookup_by_name(self, _name, lookup, expected):
        assert self._decoder_with().get_key_columns(lookup) == expected

    def test_full_replica_identity_yields_no_key(self):
        # FULL flags every column, so adopting it as the key would make the merge key the whole row
        # and every update would insert instead of replace.
        decoder = self._decoder_with(replica_identity=2, key_flags=(1, 1, 1))

        assert decoder.get_key_columns("cdc_test.orders") == []

    def test_declared_key_covering_every_column_survives(self):
        decoder = self._decoder_with(replica_identity=0, key_flags=(1, 1, 1))

        assert decoder.get_key_columns("cdc_test.orders") == ["id", "tenant_id", "total"]
