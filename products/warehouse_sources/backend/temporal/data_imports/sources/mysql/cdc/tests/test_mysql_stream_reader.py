import uuid
import datetime as dt
from collections.abc import Iterator

import pytest

import pyarrow as pa

from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.cdc.types import ChangeEvent
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc import binlog
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.adapter import MySQLCDCAdapter
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.config import (
    POSITION_KEY,
    MySQLCDCConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.errors import (
    MySQLUnsupportedBinlogError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.position import BinlogPosition
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.stream_reader import (
    MySQLCDCStreamReader,
    truncated_table,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.tests.conftest import (
    DATABASE,
    ROOT_PASSWORD,
    connect,
    global_variable,
)

pytestmark = pytest.mark.django_db

_TABLE = f"{DATABASE}.orders"


@pytest.fixture
def orders(root_conn) -> Iterator[None]:
    with root_conn.cursor() as cur:
        cur.execute(
            f"CREATE TABLE {_TABLE} (id INT PRIMARY KEY, status VARCHAR(20), meta JSON, tags SET('a','b','c'), "
            "ext_id VARBINARY(4), raw BLOB, created_at TIMESTAMP NULL)"
        )
    yield
    with root_conn.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {_TABLE}")


@pytest.fixture
def source(team, mysql_server, root_conn, orders) -> ExternalDataSource:
    return ExternalDataSource.objects.create(
        team_id=team.pk,
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        status="Completed",
        source_type="MySQL",
        job_inputs={
            "host": mysql_server.get_container_host_ip(),
            "port": int(mysql_server.get_exposed_port(3306)),
            "database": DATABASE,
            "user": "root",
            "password": ROOT_PASSWORD,
            "schema": DATABASE,
            "using_ssl": False,
            "cdc_enabled": True,
            "cdc_server_id": 424242,
            "cdc_server_uuid": binlog.server_uuid(root_conn),
            POSITION_KEY: binlog.visible_position(root_conn, epoch=3).serialize(),
        },
    )


def _execute(conn, *statements: str) -> None:
    with conn.cursor() as cur:
        for statement in statements:
            cur.execute(statement)


def _reader(source: ExternalDataSource) -> MySQLCDCStreamReader:
    source.refresh_from_db()
    reader = MySQLCDCAdapter().create_reader(source)
    assert isinstance(reader, MySQLCDCStreamReader)
    reader.connect()
    return reader


def _read(reader: MySQLCDCStreamReader, upto: int | None = None) -> list[ChangeEvent]:
    return list(reader.read_changes(upto_nchanges=upto))


def _row_ids(events: list[ChangeEvent]) -> list[int]:
    return [event.columns["id"] for event in events]


class TestMySQLCDCStreamReader:
    def test_reads_a_transaction_at_its_commit_position_with_snapshot_typed_values(
        self, source, root_conn, mysql_server
    ):
        _execute(
            root_conn,
            "BEGIN",
            f"""INSERT INTO {_TABLE} (id, status, meta, tags) VALUES (1, 'new', '{{"k": [1, 2]}}', 'c,a'), """
            "(2, 'new', NULL, NULL)",
            f"""INSERT INTO {_TABLE} VALUES (3, 'new', '"text"', '', x'0a0b', x'00', '2026-01-01 10:00:00')""",
            f"UPDATE {_TABLE} SET id = 10, status = 'paid' WHERE id = 1",
            f"DELETE FROM {_TABLE} WHERE id = 2",
            "COMMIT",
        )
        # A snapshot reads TIMESTAMP in the server's zone, while the binlog holds UTC.
        with global_variable(root_conn, "time_zone", "+02:00"):
            snapshot = connect(mysql_server)
            try:
                with snapshot.cursor() as cur:
                    cur.execute(f"SELECT created_at FROM {_TABLE} WHERE id = 3")
                    (snapshot_created_at,) = cur.fetchone()
            finally:
                snapshot.close()
            reader = _reader(source)
        reader.set_key_change_columns({_TABLE: ["id"]})
        try:
            events = _read(reader)
        finally:
            reader.close()

        assert [(e.operation, e.columns["id"]) for e in events] == [("I", 1), ("I", 2), ("I", 3), ("U", 10), ("D", 2)]
        assert len({e.position_serialized for e in events}) == 1
        commit = BinlogPosition.deserialize(events[0].position_serialized)
        assert commit.epoch == 3
        assert reader.last_commit_position == events[0].position_serialized
        assert events[0].columns["meta"] == '{"k": [1, 2]}'
        assert events[0].columns["tags"] == "a,c"
        assert events[2].columns["meta"] == '"text"'
        assert events[2].columns["tags"] == ""
        assert events[2].columns["ext_id"] == "0a0b"
        assert "raw" not in events[2].columns
        assert events[2].columns["created_at"] == snapshot_created_at
        assert events[3].previous_values == {"id": 1}
        assert events[0].column_types is not None
        assert len({id(e.column_types) for e in events}) == 1
        assert events[0].column_types["id"] == pa.int32()
        assert events[0].column_types["ext_id"] == pa.string()
        assert "raw" not in events[0].column_types
        assert events[0].timestamp.tzinfo == dt.UTC

    def test_a_savepoint_keeps_its_transaction_at_one_commit_position(self, source, root_conn):
        _execute(
            root_conn,
            "BEGIN",
            f"INSERT INTO {_TABLE} (id) VALUES (1)",
            "SAVEPOINT before_second",
            f"INSERT INTO {_TABLE} (id) VALUES (2)",
            "ROLLBACK TO SAVEPOINT before_second",
            f"INSERT INTO {_TABLE} (id) VALUES (3)",
            "COMMIT",
        )
        reader = _reader(source)
        try:
            events = _read(reader)
        finally:
            reader.close()

        assert _row_ids(events) == [1, 3]
        assert len({e.position_serialized for e in events}) == 1

    def test_rows_of_other_databases_are_not_read(self, source, root_conn):
        _execute(
            root_conn,
            "CREATE DATABASE other",
            "CREATE TABLE other.orders (id INT PRIMARY KEY)",
            "INSERT INTO other.orders VALUES (7)",
            f"INSERT INTO {_TABLE} (id) VALUES (1)",
        )
        try:
            reader = _reader(source)
            try:
                events = _read(reader)
            finally:
                reader.close()
        finally:
            _execute(root_conn, "DROP DATABASE other")

        assert [event.table_name for event in events] == [_TABLE]

    @pytest.mark.parametrize(
        "statements",
        [
            pytest.param(
                [
                    "XA START 'x1'",
                    f"INSERT INTO {_TABLE} (id) VALUES (1)",
                    "XA END 'x1'",
                    "XA PREPARE 'x1'",
                    "XA COMMIT 'x1'",
                ],
                id="xa_transaction",
            ),
            pytest.param(
                [
                    f"""INSERT INTO {_TABLE} (id, meta) VALUES (1, '{{"a": 1, "b": "{"x" * 100}"}}')""",
                    "SET SESSION binlog_row_value_options = 'PARTIAL_JSON'",
                    f"UPDATE {_TABLE} SET meta = JSON_SET(meta, '$.a', 2) WHERE id = 1",
                    "SET SESSION binlog_row_value_options = ''",
                ],
                id="partial_json_update",
            ),
        ],
    )
    def test_a_change_capture_cannot_read_stops_the_read(self, source, root_conn, statements):
        _execute(root_conn, *statements)
        reader = _reader(source)
        try:
            with pytest.raises(MySQLUnsupportedBinlogError):
                _read(reader)
        finally:
            reader.close()

    def test_a_stale_reader_does_not_move_the_stored_position_back(self, source, root_conn):
        for row_id in (1, 2):
            _execute(root_conn, f"INSERT INTO {_TABLE} (id) VALUES ({row_id})")
        ahead, stale = _reader(source), _reader(source)
        try:
            first, second = _read(ahead)
            ahead.confirm_position(second.position_serialized)
            stale.confirm_position(first.position_serialized)
        finally:
            ahead.close()
            stale.close()

        source.refresh_from_db()
        assert MySQLCDCConfig.from_source(source).position == second.position_serialized

    def test_an_unconfirmed_read_is_read_again_and_a_confirmed_one_resumes_after_it(self, source, root_conn):
        for row_id in (1, 2, 3):
            _execute(root_conn, f"INSERT INTO {_TABLE} (id, status) VALUES ({row_id}, 'new')")

        reader = _reader(source)
        try:
            first_page = _read(reader, upto=1)
            assert _row_ids(first_page) == [1]
            assert _row_ids(_read(reader, upto=1)) == [1]

            reader.confirm_position(first_page[-1].position_serialized)
            assert _row_ids(_read(reader)) == [2, 3]
        finally:
            reader.close()

        source.refresh_from_db()
        assert MySQLCDCConfig.from_source(source).position == first_page[-1].position_serialized
        resumed = _reader(source)
        try:
            assert _row_ids(_read(resumed)) == [2, 3]
        finally:
            resumed.close()

    def test_a_column_added_mid_stream_reaches_the_changes_after_it(self, source, root_conn):
        _execute(
            root_conn,
            f"INSERT INTO {_TABLE} (id, status) VALUES (1, 'new')",
            f"ALTER TABLE {_TABLE} ADD COLUMN amount DECIMAL(10, 2)",
            f"INSERT INTO {_TABLE} (id, status, amount) VALUES (2, 'new', 9.50)",
        )
        reader = _reader(source)
        try:
            before, after = _read(reader)
        finally:
            reader.close()

        assert "amount" not in before.columns
        assert str(after.columns["amount"]) == "9.50"
        assert after.column_types is not None
        assert pa.types.is_decimal(after.column_types["amount"])

    def test_truncate_is_reported_and_the_stream_moves_past_it(self, source, root_conn):
        _execute(root_conn, f"INSERT INTO {_TABLE} (id) VALUES (1)", f"TRUNCATE TABLE {_TABLE}")
        reader = _reader(source)
        try:
            [insert] = _read(reader)
            assert reader.truncated_tables == [_TABLE]
            assert reader.last_commit_position is not None
            assert BinlogPosition.deserialize(reader.last_commit_position) > BinlogPosition.deserialize(
                insert.position_serialized
            )
        finally:
            reader.close()

    def test_a_dotted_name_does_not_hide_another_tables_unique_key(self, source, root_conn):
        _execute(
            root_conn,
            f"CREATE TABLE {DATABASE}.`a` (id INT PRIMARY KEY, v INT NULL, UNIQUE KEY `b.c` (v))",
            f"CREATE TABLE {DATABASE}.`a.b` (id INT PRIMARY KEY, code INT NOT NULL, UNIQUE KEY `c` (code))",
        )
        reader = _reader(source)
        try:
            keys = reader.get_enforced_unique_keys(DATABASE, ["a", "a.b"])
        finally:
            reader.close()
            _execute(root_conn, f"DROP TABLE {DATABASE}.`a`, {DATABASE}.`a.b`")

        assert set(keys["a.b"]) == {frozenset({"id"}), frozenset({"code"})}
        assert set(keys["a"]) == {frozenset({"id"})}


@pytest.mark.parametrize(
    "statement,expected",
    [
        ("TRUNCATE TABLE app.orders", "app.orders"),
        ("truncate orders", "db.orders"),
        ("TRUNCATE TABLE app . orders", "app.orders"),
        ("TRUNCATE /* maintenance */ TABLE app.orders", "app.orders"),
        ("/* c */ TRUNCATE TABLE `app`.`weird``name`", "app.weird`name"),
        ("TRUNCATE TABLE `odd -- name`", "db.odd -- name"),
        ("DELETE FROM app.orders", None),
    ],
)
def test_truncated_table_reads_valid_truncate_syntax(statement, expected):
    assert truncated_table(statement, "db") == expected
