import socket
import threading

import pytest
from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.postgres import client_deadline
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.client_deadline import (
    client_side_deadline,
)


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
