import pytest

import psycopg

from products.warehouse_sources_queue.backend.core.batch_consumer import (
    _is_connection_refused_error,
    _is_transient_queue_db_error,
)


@pytest.mark.parametrize(
    "message, expected",
    [
        ('connection to server at "10.0.0.1", port 5432 failed: Connection refused', True),
        ("CONNECTION REFUSED", True),  # case-insensitive
        ("password authentication failed for user", False),
        ("server closed the connection unexpectedly", False),
    ],
)
def test_classifies_operational_errors(message: str, expected: bool) -> None:
    assert _is_connection_refused_error(psycopg.OperationalError(message)) is expected


def test_ignores_non_operational_errors() -> None:
    # libpq's connection refusal only ever surfaces via psycopg.OperationalError; a
    # generic exception carrying the same text must not be misclassified.
    assert _is_connection_refused_error(RuntimeError("Connection refused")) is False


def test_transient_queue_db_error_includes_connection_refused() -> None:
    # Reproduces the reported issue: the queue DB's listener is briefly down during a pod
    # restart or failover, and the startup connect gets refused outright. _connect and
    # _connect_with_startup_retry both gate their retry on this function, so a refusal
    # that isn't classified as transient crashes the consumer instead of redialing.
    error = psycopg.OperationalError('connection to server at "10.0.0.1", port 5432 failed: Connection refused')
    assert _is_transient_queue_db_error(error) is True
