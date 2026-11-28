import pytest

import psycopg

from products.warehouse_sources_queue.backend.core.batch_consumer import (
    _is_connection_refused_error,
    _is_read_only_transaction_error,
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


def test_is_read_only_transaction_error_matches_only_that_sqlstate() -> None:
    # SQLSTATE 25006: a managed-Postgres failover demotes the old primary to read-only
    # before the pooler cuts clients over, so a write arrives on a live, otherwise-healthy
    # connection and is rejected rather than dropped.
    assert _is_read_only_transaction_error(psycopg.errors.ReadOnlySqlTransaction("cannot execute DELETE")) is True
    # A connection-level failure must not be misclassified as the failover shape.
    assert _is_read_only_transaction_error(psycopg.OperationalError("connection reset by peer")) is False


def test_transient_queue_db_error_includes_read_only_transaction() -> None:
    # Reproduces the reported issue: a queue-DB failover leaves the socket open but
    # read-only for a brief window, and both the claim upsert in get_unprocessed_and_lock
    # and the lease DELETE in release_all_owned hit it. Neither is an OperationalError, so
    # without this the error isn't retried and the consumer crashes instead of redialing
    # once the failover resolves.
    error = psycopg.errors.ReadOnlySqlTransaction("cannot execute DELETE in a read-only transaction")
    assert _is_transient_queue_db_error(error) is True
