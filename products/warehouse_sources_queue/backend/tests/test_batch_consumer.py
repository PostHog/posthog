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
    # ReadOnlySqlTransaction (SQLSTATE 25006) is a DatabaseError, not an OperationalError --
    # a lookalike OperationalError (e.g. a real connection failure) must not be misclassified.
    assert _is_read_only_transaction_error(psycopg.errors.ReadOnlySqlTransaction("cannot execute SELECT")) is True
    assert _is_read_only_transaction_error(psycopg.OperationalError("cannot execute SELECT")) is False


def test_transient_queue_db_error_includes_read_only_transaction() -> None:
    # Reproduces the reported issue: a managed-Postgres failover promotes the new primary
    # before it fully exits recovery, so the claim query's locking SELECT is refused with
    # ReadOnlySqlTransaction even though the connection itself succeeded. _with_queue_conn
    # gates its retry on this function, and _report_queue_failure gates whether the error
    # reaches error tracking on it -- unclassified, this error skips the retry and (before
    # the run() loop also learned to catch non-OperationalError queue errors) crashed the
    # whole consumer instead of redialing onto the now-writable primary.
    error = psycopg.errors.ReadOnlySqlTransaction("cannot execute SELECT in a read-only transaction")
    assert _is_transient_queue_db_error(error) is True
