import pytest

import psycopg

from products.warehouse_destinations.backend.destinations.postgres.errors import (
    PERMISSIONS_DETAIL,
    MissingPrimaryKeyError,
    PostgreSQLConnectionConfigurationError,
    PostgreSQLConnectionError,
    PostgreSQLIncompatibleSchemaError,
    PostgreSQLMergeTimeoutError,
    PostgreSQLTransactionError,
    PostgreSQLUnrelatedTableError,
    translate_error,
)
from products.warehouse_destinations.backend.facade.contracts import DestinationConfigurationError, DestinationError
from products.warehouse_destinations.backend.facade.enums import ErrorKind


@pytest.mark.parametrize(
    "error, kind",
    [
        (psycopg.errors.InsufficientPrivilege("x"), ErrorKind.CONFIGURATION),
        (psycopg.errors.InvalidSchemaName("x"), ErrorKind.CONFIGURATION),
        (psycopg.errors.UndefinedTable("x"), ErrorKind.CONFIGURATION),
        (psycopg.errors.ReadOnlySqlTransaction("x"), ErrorKind.CONFIGURATION),
        (psycopg.errors.DiskFull("x"), ErrorKind.CONFIGURATION),
        (psycopg.errors.UniqueViolation("x"), ErrorKind.DATA),
        (psycopg.errors.NotNullViolation("x"), ErrorKind.DATA),
        (psycopg.errors.InvalidTextRepresentation("x"), ErrorKind.DATA),
        (psycopg.errors.DatatypeMismatch("x"), ErrorKind.DATA),
        (psycopg.errors.UndefinedColumn("x"), ErrorKind.DATA),
        (psycopg.errors.ProgramLimitExceeded("x"), ErrorKind.DATA),
        (psycopg.errors.QueryCanceled("x"), ErrorKind.TIMEOUT),
        (psycopg.errors.LockNotAvailable("x"), ErrorKind.TIMEOUT),
        (TimeoutError(), ErrorKind.TIMEOUT),
        (psycopg.errors.SerializationFailure("x"), ErrorKind.TRANSIENT),
        (psycopg.errors.DeadlockDetected("x"), ErrorKind.TRANSIENT),
        (psycopg.errors.AdminShutdown("x"), ErrorKind.TRANSIENT),
        (psycopg.OperationalError("connection dropped"), ErrorKind.TRANSIENT),
        (psycopg.InterfaceError("connection closed"), ErrorKind.TRANSIENT),
        (KeyError("unknown"), ErrorKind.TRANSIENT),
    ],
)
def test_driver_errors_translate_to_a_kind(error: Exception, kind: ErrorKind) -> None:
    translated = translate_error(error)

    assert isinstance(translated, DestinationError)
    assert translated.kind == kind
    assert translated.retryable is (kind == ErrorKind.TRANSIENT)


def test_insufficient_privilege_tells_the_customer_what_to_grant() -> None:
    assert translate_error(psycopg.errors.InsufficientPrivilege("x")).detail == PERMISSIONS_DETAIL


@pytest.mark.parametrize(
    "error, kind, configuration",
    [
        (PostgreSQLConnectionError("x"), ErrorKind.TRANSIENT, False),
        (PostgreSQLConnectionConfigurationError("Fix it."), ErrorKind.CONFIGURATION, True),
        (PostgreSQLIncompatibleSchemaError("x"), ErrorKind.DATA, False),
        (MissingPrimaryKeyError("s.t", ("id",)), ErrorKind.DATA, False),
        (PostgreSQLUnrelatedTableError("x"), ErrorKind.CONFIGURATION, True),
        (PostgreSQLTransactionError(3, "x"), ErrorKind.TRANSIENT, False),
        (PostgreSQLMergeTimeoutError("x"), ErrorKind.TIMEOUT, False),
    ],
)
def test_named_errors_keep_their_kind_and_pass_through(
    error: DestinationError, kind: ErrorKind, configuration: bool
) -> None:
    assert translate_error(error) is error
    assert error.kind == kind
    assert isinstance(error, DestinationConfigurationError) is configuration


def test_connection_configuration_error_keeps_the_marker_and_detail() -> None:
    error = PostgreSQLConnectionConfigurationError("Check the host.")

    assert str(error) == "Destination configuration error. Check the host."
    assert error.detail == "Check the host."
    assert isinstance(error, PostgreSQLConnectionError)
