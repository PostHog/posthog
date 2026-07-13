import pytest
from unittest import mock
from unittest.mock import patch

import psycopg
import psycopg.errors

from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.stream_reader import (
    _SLOT_READ_MAX_ATTEMPTS,
    PgCDCConnectionParams,
    PgCDCStreamReader,
)


@pytest.fixture
def params():
    return PgCDCConnectionParams(
        host="localhost",
        port=5432,
        database="postgres",
        user="postgres",
        password="password",
        slot_name="posthog_slot",
        publication_name="posthog_pub",
    )


def _params(require_ssl: bool) -> PgCDCConnectionParams:
    return PgCDCConnectionParams(
        host="localhost",
        port=5432,
        database="postgres",
        user="postgres",
        password="password",
        require_ssl=require_ssl,
        slot_name="posthog_slot",
        publication_name="posthog_pub",
    )


class TestPgCDCStreamReaderSSL:
    @pytest.mark.parametrize("require_ssl", [True, False])
    def test_connect_forwards_require_ssl(self, require_ssl):
        connect = mock.MagicMock(return_value=mock.MagicMock())
        reader = PgCDCStreamReader(_params(require_ssl))
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.stream_reader._connect_to_postgres",
            connect,
        ):
            reader.connect()

        assert connect.call_args.kwargs["require_ssl"] is require_ssl

    @pytest.mark.parametrize("require_ssl", [True, False])
    def test_confirm_position_forwards_require_ssl(self, require_ssl):
        connect = mock.MagicMock(return_value=mock.MagicMock())
        reader = PgCDCStreamReader(_params(require_ssl))
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.stream_reader._connect_to_postgres",
            connect,
        ):
            reader.confirm_position("0/1234ABCD")

        assert connect.call_args.kwargs["require_ssl"] is require_ssl


class TestPgCDCStreamReaderConnect:
    def test_connect_retries_transient_dropped_connection(self, params):
        good_conn = mock.MagicMock()
        connect = mock.MagicMock(
            side_effect=[
                # The exact transient drop surfaced in production when the SSH tunnel /
                # pooler closes the first connection before it is established.
                psycopg.OperationalError("server closed the connection unexpectedly"),
                good_conn,
            ]
        )

        reader = PgCDCStreamReader(params)
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.stream_reader._connect_to_postgres",
                connect,
            ),
            patch("products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.time.sleep"),
        ):
            reader.connect()

        assert reader._conn is good_conn
        assert connect.call_count == 2

    def test_connect_does_not_retry_permanent_error(self, params):
        connect = mock.MagicMock(
            side_effect=psycopg.OperationalError(
                'connection to server at "10.0.0.1" failed: FATAL: password authentication failed'
            )
        )

        reader = PgCDCStreamReader(params)
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.stream_reader._connect_to_postgres",
                connect,
            ),
            patch("products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.time.sleep"),
        ):
            with pytest.raises(psycopg.OperationalError):
                reader.connect()

        assert connect.call_count == 1


class TestPgCDCStreamReaderConnectOptions:
    def test_connect_sets_streaming_timeouts(self, params):
        connect = mock.MagicMock(return_value=mock.MagicMock())
        reader = PgCDCStreamReader(params)
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.stream_reader._connect_to_postgres",
            connect,
        ):
            reader.connect()

        options = connect.call_args.kwargs["options"]
        # A stalled server-side WAL decode can't hang the streaming connection indefinitely.
        assert "statement_timeout=1800000" in options
        # The named cursor holds a transaction open while the caller flushes between yields, so the
        # source must not cull the backend (SQLSTATE 25P03) for sitting idle in that transaction.
        assert "idle_in_transaction_session_timeout=0" in options


class TestPgCDCStreamReaderReadChanges:
    def _reader_serving(self, params, rows):
        reader = PgCDCStreamReader(params)
        fake_cursor = mock.MagicMock()
        fake_cursor.__iter__.return_value = iter(rows)
        reader._conn = mock.MagicMock()
        reader._conn.cursor.return_value.__enter__.return_value = fake_cursor
        # Isolate the read mechanics (row count + callback) from pgoutput decoding.
        reader._decoder = mock.MagicMock()
        reader._decoder.decode_message.return_value = []
        return reader, fake_cursor

    def test_read_changes_bounds_peek_with_upto_nchanges(self, params):
        reader, fake_cursor = self._reader_serving(params, [])
        list(reader.read_changes(upto_nchanges=100_000))
        rendered = fake_cursor.execute.call_args.args[0].as_string(None)
        # Third positional arg of pg_logical_slot_peek_binary_changes is the change cap.
        assert ", NULL, 100000, " in rendered

    def test_read_changes_passes_null_when_unbounded(self, params):
        reader, fake_cursor = self._reader_serving(params, [])
        list(reader.read_changes())
        rendered = fake_cursor.execute.call_args.args[0].as_string(None)
        assert ", NULL, NULL, " in rendered

    def test_read_changes_invokes_on_row_per_row_and_counts(self, params):
        rows = [("0/1", 1, b"a"), ("0/2", 1, b"b"), ("0/3", 1, b"c")]
        reader, _ = self._reader_serving(params, rows)
        on_row_calls = 0

        def on_row() -> None:
            nonlocal on_row_calls
            on_row_calls += 1

        list(reader.read_changes(upto_nchanges=10, on_row=on_row))

        assert on_row_calls == len(rows)
        assert reader.last_rows_consumed == len(rows)


class TestPgCDCStreamReaderReadChangesSlotInUse:
    def _reader_reading(self, params, iter_side_effect):
        reader = PgCDCStreamReader(params)
        fake_cursor = mock.MagicMock()
        fake_cursor.__iter__.side_effect = iter_side_effect
        reader._conn = mock.MagicMock()
        reader._conn.cursor.return_value.__enter__.return_value = fake_cursor
        # Isolate the read mechanics (retry + row count) from pgoutput decoding.
        reader._decoder = mock.MagicMock()
        reader._decoder.decode_message.return_value = []
        return reader, fake_cursor

    def test_read_changes_retries_slot_in_use_then_succeeds(self, params):
        # A prior run's connection is still releasing the slot on the first fetch; the next
        # attempt self-heals instead of failing the whole extraction.
        rows = [("0/1", 1, b"a"), ("0/2", 1, b"b")]
        reader, fake_cursor = self._reader_reading(
            params,
            [
                psycopg.errors.ObjectInUse('replication slot "posthog_slot" is active for PID 2999'),
                iter(rows),
            ],
        )
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.stream_reader.time.sleep"
        ) as sleep:
            list(reader.read_changes(upto_nchanges=10))

        assert fake_cursor.__iter__.call_count == 2
        assert reader.last_rows_consumed == len(rows)
        # First backoff is 0.5 * 2**0 — asserting the value locks the multiplier.
        sleep.assert_called_once_with(0.5)
        reader._conn.rollback.assert_called_once()

    def test_read_changes_reraises_when_slot_stays_in_use(self, params):
        # A slot that never frees exhausts the in-process retries and re-raises, so the run still
        # surfaces as the retryable SLOT_IN_USE classification rather than looping or silently
        # returning no changes.
        reader, fake_cursor = self._reader_reading(
            params,
            psycopg.errors.ObjectInUse('replication slot "posthog_slot" is active for PID 2999'),
        )
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.stream_reader.time.sleep"
        ) as sleep:
            with pytest.raises(psycopg.errors.ObjectInUse):
                list(reader.read_changes(upto_nchanges=10))

        assert fake_cursor.__iter__.call_count == _SLOT_READ_MAX_ATTEMPTS
        assert sleep.call_count == _SLOT_READ_MAX_ATTEMPTS - 1

    def test_read_changes_does_not_retry_unrelated_object_in_use(self, params):
        # A different SQLSTATE 55006 (not the transient slot handoff) is re-raised immediately,
        # never retried, so an unrelated failure isn't silently delayed.
        reader, fake_cursor = self._reader_reading(
            params,
            psycopg.errors.ObjectInUse("database is being accessed by other users"),
        )
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.stream_reader.time.sleep"
        ) as sleep:
            with pytest.raises(psycopg.errors.ObjectInUse):
                list(reader.read_changes(upto_nchanges=10))

        assert fake_cursor.__iter__.call_count == 1
        sleep.assert_not_called()


class TestPgCDCStreamReaderConfirmPosition:
    def test_confirm_position_retries_transient_dropped_connection(self, params):
        good_conn = mock.MagicMock()
        connect = mock.MagicMock(
            side_effect=[
                # The short-lived slot-advance connection reaches the source through the
                # same tunnel / pooler as the initial connect, so it can hit the same
                # transient drop while advancing the replication slot after a run.
                psycopg.OperationalError("server closed the connection unexpectedly"),
                good_conn,
            ]
        )

        reader = PgCDCStreamReader(params)
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.stream_reader._connect_to_postgres",
                connect,
            ),
            patch("products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.time.sleep"),
        ):
            reader.confirm_position("0/1234ABCD")

        assert connect.call_count == 2
        good_conn.commit.assert_called_once()
        good_conn.close.assert_called_once()

    def test_confirm_position_does_not_retry_permanent_error(self, params):
        connect = mock.MagicMock(
            side_effect=psycopg.OperationalError(
                'connection to server at "10.0.0.1" failed: FATAL: password authentication failed'
            )
        )

        reader = PgCDCStreamReader(params)
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.stream_reader._connect_to_postgres",
                connect,
            ),
            patch("products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.time.sleep"),
        ):
            with pytest.raises(psycopg.OperationalError):
                reader.confirm_position("0/1234ABCD")

        assert connect.call_count == 1

    def _reader_advancing(self, params, execute_side_effect):
        conn = mock.MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.execute.side_effect = execute_side_effect
        connect = mock.MagicMock(return_value=conn)
        reader = PgCDCStreamReader(params)
        return reader, conn, cur, connect

    def test_confirm_position_retries_while_slot_active(self, params):
        # The slot is momentarily held while the streaming peek releases it; the advance
        # self-heals on the next attempt instead of failing the whole extraction.
        reader, conn, cur, connect = self._reader_advancing(
            params,
            [psycopg.errors.ObjectInUse('replication slot "posthog_slot" is active for PID 2999'), None],
        )
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.stream_reader._connect_to_postgres",
                connect,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.stream_reader.time.sleep"
            ),
        ):
            reader.confirm_position("0/1234ABCD")

        assert cur.execute.call_count == 2
        # The failed advance aborts the transaction, so the retry must reset it first or real
        # psycopg raises InFailedSqlTransaction.
        conn.rollback.assert_called_once()
        conn.commit.assert_called_once()
        conn.close.assert_called_once()

    def test_confirm_position_raises_when_slot_stays_active(self, params):
        # A slot that never frees exhausts the in-process retries and re-raises, so the run
        # still surfaces as the retryable SLOT_IN_USE classification rather than looping forever.
        reader, conn, cur, connect = self._reader_advancing(
            params,
            psycopg.errors.ObjectInUse('replication slot "posthog_slot" is active for PID 2999'),
        )
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.stream_reader._connect_to_postgres",
                connect,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.stream_reader.time.sleep"
            ),
        ):
            with pytest.raises(psycopg.errors.ObjectInUse):
                reader.confirm_position("0/1234ABCD")

        assert cur.execute.call_count == 3
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_confirm_position_tolerates_slot_already_ahead(self, params):
        # A retried / overlapping run advanced the slot further, so Postgres refuses the backward
        # advance. The WAL is already released past this LSN, so it must be a no-op, not a failure.
        conn = mock.MagicMock()
        conn.cursor.return_value.__enter__.return_value.execute.side_effect = (
            psycopg.errors.ObjectNotInPrerequisiteState(
                "cannot advance replication slot to B4/C7327D08, minimum is B4/CB22FB98"
            )
        )
        connect = mock.MagicMock(return_value=conn)

        reader = PgCDCStreamReader(params)
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.stream_reader._connect_to_postgres",
            connect,
        ):
            reader.confirm_position("B4/C7327D08")

        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    def test_confirm_position_reraises_other_prerequisite_errors(self, params):
        # Slot invalidation is also ObjectNotInPrerequisiteState but must keep propagating so the
        # slot gets recreated — only the "already ahead" case is swallowed.
        conn = mock.MagicMock()
        conn.cursor.return_value.__enter__.return_value.execute.side_effect = (
            psycopg.errors.ObjectNotInPrerequisiteState(
                "cannot advance replication slot that has not previously reserved WAL"
            )
        )
        connect = mock.MagicMock(return_value=conn)

        reader = PgCDCStreamReader(params)
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.stream_reader._connect_to_postgres",
            connect,
        ):
            with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
                reader.confirm_position("B4/C7327D08")

        conn.close.assert_called_once()
