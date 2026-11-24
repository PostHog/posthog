import threading

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc import binlog
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.position import BinlogPosition
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.tests.conftest import DATABASE, connect


@pytest.fixture
def table(root_conn):
    with root_conn.cursor() as cur:
        cur.execute(f"CREATE TABLE {DATABASE}.events (id INT PRIMARY KEY, payload TEXT)")
    yield f"{DATABASE}.events"
    with root_conn.cursor() as cur:
        cur.execute(f"DROP TABLE {DATABASE}.events")


def _execute(conn, *statements):
    with conn.cursor() as cur:
        for statement in statements:
            cur.execute(statement)


class TestVisiblePosition:
    def test_waits_for_a_writing_transaction_open_when_the_position_was_read(self, mysql_server, root_conn, table):
        writer = connect(mysql_server)
        _execute(writer, "BEGIN", f"INSERT INTO {table} VALUES (1, 'a')")
        result: list[BinlogPosition] = []
        reader = threading.Thread(target=lambda: result.append(binlog.visible_position(root_conn, epoch=0)))
        reader.start()
        try:
            reader.join(timeout=1)
            assert reader.is_alive()
        finally:
            _execute(writer, "COMMIT")
            writer.close()
        reader.join(timeout=10)
        assert not reader.is_alive()
        assert result[0].file == binlog.binlog_status(root_conn)[0]

    def test_a_transaction_list_cached_before_the_position_is_not_trusted(
        self, mysql_server, root_conn, table, monkeypatch
    ):
        monkeypatch.setattr(binlog, "_VISIBILITY_TIMEOUT_SECONDS", 2.0)
        # A session that reads INNODB_TRX more often than every 0.1 s keeps its cache from refreshing.
        first_read, stop = threading.Event(), threading.Event()

        def keep_reading() -> None:
            conn = connect(mysql_server)
            try:
                while not stop.is_set():
                    _execute(conn, "SELECT COUNT(*) FROM information_schema.INNODB_TRX")
                    first_read.set()
            finally:
                conn.close()

        reader = threading.Thread(target=keep_reading)
        reader.start()
        writer = connect(mysql_server)
        try:
            assert first_read.wait(timeout=10)
            _execute(writer, "BEGIN", f"INSERT INTO {table} VALUES (1, 'a')")
            with pytest.raises(binlog.BinlogPositionNotVisibleError):
                binlog.visible_position(root_conn, epoch=0)
        finally:
            stop.set()
            reader.join(timeout=10)
            _execute(writer, "ROLLBACK")
            writer.close()


class TestRequireReadable:
    def test_position_in_a_purged_file_is_lost(self, root_conn, table):
        old = binlog.visible_position(root_conn, epoch=0)
        binlog.require_readable(root_conn, old, binlog.server_uuid(root_conn))

        _execute(root_conn, "FLUSH BINARY LOGS")
        current_file, _ = binlog.binlog_status(root_conn)
        _execute(root_conn, f"PURGE BINARY LOGS TO '{current_file}'")

        with pytest.raises(binlog.BinlogStreamLostError, match="purged"):
            binlog.require_readable(root_conn, old, binlog.server_uuid(root_conn))

    def test_another_server_is_a_lost_stream(self, root_conn):
        position = binlog.visible_position(root_conn, epoch=0)
        with pytest.raises(binlog.BinlogStreamLostError, match="another MySQL server"):
            binlog.require_readable(root_conn, position, "00000000-0000-0000-0000-000000000000")


class TestLagBytes:
    def test_counts_the_rest_of_the_file_and_every_later_file(self, root_conn, table):
        position = binlog.visible_position(root_conn, epoch=0)
        _execute(root_conn, f"INSERT INTO {table} VALUES (1, REPEAT('x', 5000))", "FLUSH BINARY LOGS")
        _execute(root_conn, f"INSERT INTO {table} VALUES (2, REPEAT('y', 5000))")

        sizes = {file.name: file.size for file in binlog.binary_logs(root_conn)}
        current_file, current_offset = binlog.binlog_status(root_conn)

        lag = binlog.lag_bytes(root_conn, position)

        assert lag == sizes[position.file] - position.offset + current_offset
        assert lag > 10_000
        assert current_file != position.file
