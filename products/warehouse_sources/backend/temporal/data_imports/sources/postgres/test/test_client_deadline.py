import socket
import threading

import pytest
from unittest.mock import MagicMock, patch

import psycopg

from products.warehouse_sources.backend.temporal.data_imports.external_data_job import Any_Source_Errors
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.neon.source import NeonSource
from products.warehouse_sources.backend.temporal.data_imports.sources.planetscale_postgres.source import (
    PlanetScalePostgresSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres import client_deadline
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.client_deadline import (
    ClientDeadlineExceededError,
    client_side_deadline,
    deadline_server_cursor_factory,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source import PostgresSource
from products.warehouse_sources.backend.temporal.data_imports.sources.supabase.source import SupabaseSource


def test_a_statement_that_ends_in_time_is_not_cancelled() -> None:
    connection = MagicMock()

    with client_side_deadline(connection, timeout_seconds=30):
        pass

    connection.cancel_safe.assert_not_called()


def test_a_statement_past_the_deadline_gets_a_cancel_request() -> None:
    cancelled = threading.Event()
    connection = MagicMock()
    connection.cancel_safe.side_effect = lambda timeout: cancelled.set()

    with client_side_deadline(connection, timeout_seconds=0.01):
        assert cancelled.wait(5)

    connection.cancel_safe.assert_called_once_with(timeout=client_deadline.CANCEL_REQUEST_TIMEOUT_SECONDS)


@pytest.mark.parametrize(
    "cancel_error",
    [None, RuntimeError("cancel request refused")],
    ids=["cancel_ignored_by_server", "cancel_request_fails"],
)
def test_a_statement_that_ignores_the_cancel_request_loses_its_socket(
    monkeypatch: pytest.MonkeyPatch, cancel_error: Exception | None
) -> None:
    monkeypatch.setattr(client_deadline, "CANCEL_GRACE_SECONDS", 0.01)
    client_end, server_end = socket.socketpair()
    client_end.settimeout(5)
    connection = MagicMock()
    connection.fileno.return_value = client_end.fileno()
    connection.cancel_safe.side_effect = cancel_error

    try:
        with client_side_deadline(connection, timeout_seconds=0.01):
            # A blocked read on the socket of the connection, as in a statement the server never answers.
            assert client_end.recv(1) == b""
    finally:
        client_end.close()
        server_end.close()


def _statement_ended_by_the_deadline(connection: MagicMock, error: Exception, **deadline_kwargs: bool) -> None:
    cancelled = threading.Event()
    connection.cancel_safe.side_effect = lambda timeout: cancelled.set()
    with client_side_deadline(connection, timeout_seconds=0.01, **deadline_kwargs):
        assert cancelled.wait(5)
        raise error


@pytest.mark.parametrize(
    "statement_error",
    [
        psycopg.errors.QueryCanceled("canceling statement due to user request"),
        psycopg.OperationalError("consuming input failed: server closed the connection unexpectedly"),
    ],
    ids=["after_the_cancel_request", "after_the_socket_shutdown"],
)
def test_a_statement_ended_by_the_deadline_raises_the_deadline_error(statement_error: Exception) -> None:
    with pytest.raises(ClientDeadlineExceededError) as error:
        _statement_ended_by_the_deadline(MagicMock(), statement_error)

    assert error.value.__cause__ is statement_error


def test_a_statement_ended_by_the_deadline_can_keep_its_own_error() -> None:
    statement_error = psycopg.errors.QueryCanceled("canceling statement due to user request")

    with pytest.raises(psycopg.errors.QueryCanceled):
        _statement_ended_by_the_deadline(MagicMock(), statement_error, raise_deadline_error=False)


def test_a_statement_that_fails_before_the_deadline_keeps_its_own_error() -> None:
    with pytest.raises(psycopg.errors.UndefinedTable):
        with client_side_deadline(MagicMock(), timeout_seconds=30):
            raise psycopg.errors.UndefinedTable("relation does not exist")


class _RecordingTimer:
    started: list[float] = []
    cancelled = 0

    def __init__(self, interval: float, function: object) -> None:
        self.interval = interval
        self.daemon = False

    def start(self) -> None:
        type(self).started.append(self.interval)

    def cancel(self) -> None:
        type(self).cancelled += 1


@pytest.mark.parametrize(
    "round_trip",
    [
        lambda cursor: cursor.execute("SELECT 1"),
        lambda cursor: cursor.fetchone(),
        lambda cursor: cursor.fetchmany(100),
        lambda cursor: cursor.fetchall(),
        lambda cursor: cursor.close(),
    ],
    ids=["execute", "fetchone", "fetchmany", "fetchall", "close"],
)
def test_each_server_cursor_round_trip_gets_its_own_deadline(monkeypatch: pytest.MonkeyPatch, round_trip) -> None:
    # A deadline that covered the read as a whole would end a long read that is in good health.
    _RecordingTimer.started = []
    _RecordingTimer.cancelled = 0
    monkeypatch.setattr(client_deadline.threading, "Timer", _RecordingTimer)
    cursor_class = deadline_server_cursor_factory(660)
    cursor = cursor_class.__new__(cursor_class)
    cursor._conn = MagicMock()

    with (
        patch.object(psycopg.ServerCursor, "execute"),
        patch.object(psycopg.ServerCursor, "fetchone"),
        patch.object(psycopg.ServerCursor, "fetchmany"),
        patch.object(psycopg.ServerCursor, "fetchall"),
        patch.object(psycopg.ServerCursor, "close"),
    ):
        for _ in range(3):
            round_trip(cursor)

    assert _RecordingTimer.started == [660, 660, 660]
    assert _RecordingTimer.cancelled == 3


@pytest.mark.parametrize(
    "round_trip,expected_error",
    [
        (lambda cursor: cursor.fetchmany(100), ClientDeadlineExceededError),
        # The row generator closes its cursor while it unwinds, and its callers handle the native error.
        (lambda cursor: cursor.close(), psycopg.errors.QueryCanceled),
    ],
    ids=["fetchmany", "close"],
)
def test_a_silent_server_cursor_round_trip_ends_at_the_deadline(round_trip, expected_error) -> None:
    cancelled = threading.Event()
    connection = MagicMock()
    connection.cancel_safe.side_effect = lambda timeout: cancelled.set()
    cursor_class = deadline_server_cursor_factory(0.01)
    cursor = cursor_class.__new__(cursor_class)
    cursor._conn = connection

    def silent_until_cancelled(*args: object) -> None:
        assert cancelled.wait(5)
        raise psycopg.errors.QueryCanceled("canceling statement due to user request")

    with (
        patch.object(psycopg.ServerCursor, "fetchmany", side_effect=silent_until_cancelled),
        patch.object(psycopg.ServerCursor, "close", side_effect=silent_until_cancelled),
        pytest.raises(expected_error),
    ):
        round_trip(cursor)


@pytest.mark.parametrize("source_class", [PostgresSource, NeonSource, SupabaseSource, PlanetScalePostgresSource])
def test_the_deadline_error_is_retryable_for_every_postgres_source(source_class: type[PostgresSource]) -> None:
    source = source_class()
    message = str(ClientDeadlineExceededError(660))

    assert not error_message_matches(message, {**Any_Source_Errors, **source.get_non_retryable_errors()})
    assert error_message_matches(message, source.get_retryable_errors())
    assert error_message_matches(message, source.get_retry_exhausted_errors())
