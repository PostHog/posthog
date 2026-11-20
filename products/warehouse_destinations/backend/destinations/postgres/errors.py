"""Errors the Postgres destination raises, and how driver errors map onto error kinds.

Callers decide what to do from `DestinationError.kind`. The class names stay stable (for
example `PostgreSQLConnectionError` or `MissingPrimaryKeyError`) only so that code that still
matches on names keeps working while it moves to `kind`.
"""

import psycopg

from products.warehouse_destinations.backend.facade.contracts import DestinationConfigurationError, DestinationError
from products.warehouse_destinations.backend.facade.enums import ErrorKind

PERMISSIONS_DETAIL = (
    "The Postgres user lacks permissions. Grant it USAGE and CREATE on the schema, and SELECT, "
    "INSERT, UPDATE and DELETE on its tables."
)
MISSING_SCHEMA_DETAIL = "The schema does not exist, or the Postgres user cannot see it."
MISSING_TABLE_DETAIL = "A table does not exist, or the Postgres user cannot see it."
READ_ONLY_DETAIL = "The database does not accept writes. Use a primary server that is not read-only."
DISK_FULL_DETAIL = "The database server is out of disk space."
ROUTINE_DETAIL = "A function or trigger on the destination database raised an error."
TIMEOUT_DETAIL = "The database canceled a statement that ran longer than its time limit."
TRANSIENT_DETAIL = "The connection to the database failed. PostHog will try again."
UNSUPPORTED_DETAIL = "The database does not support an operation this destination needs."
AUTHENTICATION_DETAIL = "The database refused the user name or password."
UNKNOWN_DATABASE_DETAIL = "The database does not exist on this server."
LOCK_DETAIL = "A statement waited too long for a lock that another session holds."
CONFLICT_DETAIL = "A concurrent transaction conflicted with this write. PostHog will try again."
DEADLOCK_DETAIL = "The database found a deadlock with another session. PostHog will try again."
UNDEFINED_COLUMN_DETAIL = "A column does not exist in the destination table."
DATATYPE_MISMATCH_DETAIL = "A column of the destination table has a type that does not match the data."
SIZE_LIMIT_DETAIL = "A value or a row is larger than a limit of the database."
DUPLICATE_KEY_DETAIL = "The data has more than one row with the same merge key."
INVALID_VALUE_DETAIL = "A value does not fit the type or the limits of its column (SQLSTATE {sqlstate})."
CONSTRAINT_DETAIL = "A row breaks a constraint of the destination table (SQLSTATE {sqlstate})."
DATABASE_ERROR_DETAIL = "The database refused a statement (SQLSTATE {sqlstate})."


class PostgreSQLConnectionError(DestinationError):
    """The client could not connect after its retries, or the connection dropped."""

    default_kind = ErrorKind.TRANSIENT


class PostgreSQLConnectionConfigurationError(PostgreSQLConnectionError, DestinationConfigurationError):
    """The connection settings stop every connection attempt, so a retry cannot succeed."""

    default_kind = ErrorKind.CONFIGURATION

    def __init__(self, detail: str) -> None:
        super().__init__(f"Destination configuration error. {detail}", detail=detail)


class PostgreSQLIntegrationNotFoundError(DestinationConfigurationError):
    """The integration that holds the connection details does not exist."""


class PostgreSQLMissingRequiredInputsError(DestinationConfigurationError):
    """The connection is missing required details, for example the host or the password."""

    def __init__(self, err_msg: str) -> None:
        message = f"The connection is missing required inputs: {err_msg}"
        super().__init__(message, detail=message)


class PostgreSQLIncompatibleSchemaError(DestinationError):
    """The destination table schema does not match the schema of the data."""

    default_kind = ErrorKind.DATA

    def __init__(self, err_msg: str) -> None:
        message = f"The data is incompatible with the schema of the destination table: {err_msg}"
        super().__init__(message, detail=message)


class PostgreSQLInvalidTargetError(DestinationConfigurationError):
    """The target cannot work in Postgres, for example a name that is too long."""

    def __init__(self, message: str) -> None:
        super().__init__(message, detail=message)


class PostgreSQLUnrelatedTableError(DestinationConfigurationError):
    """A write would change a table that does not carry the owner tag of the target."""

    def __init__(self, message: str) -> None:
        super().__init__(message, detail=message)


class MissingPrimaryKeyError(DestinationError):
    """A merge target has no unique key on the merge keys."""

    default_kind = ErrorKind.DATA

    def __init__(self, table: str, primary_key: tuple[str, ...]) -> None:
        message = (
            f"An operation could not be completed as '{table}' is missing a primary key on {', '.join(primary_key)}"
        )
        super().__init__(message, detail=message)


class ColumnTypeMappingError(DestinationError, TypeError):
    """No Postgres type exists for an Arrow type under the strict type policy."""

    default_kind = ErrorKind.DATA

    def __init__(self, destination: str, column: str, column_type: object) -> None:
        self.destination = destination
        self.column = column
        self.column_type = str(column_type)
        message = f"No {destination} type mapping for column '{column}' with Arrow type '{column_type}'."
        super().__init__(message, detail=message)


class PostgreSQLTransactionError(DestinationError):
    """A transaction failed to complete after a number of retries."""

    default_kind = ErrorKind.TRANSIENT

    def __init__(self, max_attempts: int, err_msg: str) -> None:
        super().__init__(f"A transaction failed to complete after {max_attempts} attempts: {err_msg}")


class PostgreSQLMergeTimeoutError(DestinationError):
    """The merge waited on locks or hit the statement timeout after a number of attempts."""

    default_kind = ErrorKind.TIMEOUT

    def __init__(self, message: str) -> None:
        super().__init__(message, detail=message)


class PostgreSQLLockTimeoutError(DestinationError):
    """A commit waited too long for a lock on the final table. A later attempt can get it."""

    default_kind = ErrorKind.TRANSIENT

    def __init__(self, message: str) -> None:
        super().__init__(message, detail=LOCK_DETAIL)


class PostgreSQLOperationError(DestinationError):
    """A driver error from a statement, translated into a kind. The driver error is the cause."""


# Checked in order, so a subclass must come before its base class. QueryCanceled and the
# classes 53 to 55 subclass OperationalError, which is TRANSIENT otherwise.
#
# The server's own text can quote row values (for example "invalid input syntax for type integer:
# "<value>""), so the customer-facing detail is a fixed text per class. The server text stays in
# the exception message, for logs only.
_KINDS: tuple[tuple[type[BaseException], ErrorKind, str | None], ...] = (
    (psycopg.errors.InsufficientPrivilege, ErrorKind.CONFIGURATION, PERMISSIONS_DETAIL),
    (psycopg.errors.InvalidSchemaName, ErrorKind.CONFIGURATION, MISSING_SCHEMA_DETAIL),
    (psycopg.errors.UndefinedTable, ErrorKind.CONFIGURATION, MISSING_TABLE_DETAIL),
    (psycopg.errors.ReadOnlySqlTransaction, ErrorKind.CONFIGURATION, READ_ONLY_DETAIL),
    (psycopg.errors.FeatureNotSupported, ErrorKind.CONFIGURATION, UNSUPPORTED_DETAIL),
    (psycopg.errors.DiskFull, ErrorKind.CONFIGURATION, DISK_FULL_DETAIL),
    (psycopg.errors.SqlRoutineException, ErrorKind.CONFIGURATION, ROUTINE_DETAIL),
    (psycopg.errors.InvalidPassword, ErrorKind.CONFIGURATION, AUTHENTICATION_DETAIL),
    (psycopg.errors.InvalidAuthorizationSpecification, ErrorKind.CONFIGURATION, AUTHENTICATION_DETAIL),
    (psycopg.errors.InvalidCatalogName, ErrorKind.CONFIGURATION, UNKNOWN_DATABASE_DETAIL),
    (psycopg.errors.QueryCanceled, ErrorKind.TIMEOUT, TIMEOUT_DETAIL),
    (psycopg.errors.LockNotAvailable, ErrorKind.TIMEOUT, LOCK_DETAIL),
    (psycopg.errors.SerializationFailure, ErrorKind.TRANSIENT, CONFLICT_DETAIL),
    (psycopg.errors.DeadlockDetected, ErrorKind.TRANSIENT, DEADLOCK_DETAIL),
    (psycopg.errors.UndefinedColumn, ErrorKind.DATA, UNDEFINED_COLUMN_DETAIL),
    (psycopg.errors.DatatypeMismatch, ErrorKind.DATA, DATATYPE_MISMATCH_DETAIL),
    (psycopg.errors.ProgramLimitExceeded, ErrorKind.DATA, SIZE_LIMIT_DETAIL),
    (psycopg.errors.CardinalityViolation, ErrorKind.DATA, DUPLICATE_KEY_DETAIL),
    (psycopg.DataError, ErrorKind.DATA, INVALID_VALUE_DETAIL),
    (psycopg.IntegrityError, ErrorKind.DATA, CONSTRAINT_DETAIL),
    (psycopg.OperationalError, ErrorKind.TRANSIENT, TRANSIENT_DETAIL),
    (psycopg.InterfaceError, ErrorKind.TRANSIENT, TRANSIENT_DETAIL),
    (TimeoutError, ErrorKind.TIMEOUT, None),
)


def translate_error(err: Exception) -> DestinationError:
    """Return the `DestinationError` that replaces `err` at the session boundary.

    The caller raises the result `from err`. A `DestinationError` is returned unchanged. An
    error this table does not know is TRANSIENT, so that callers retry it a bounded number of
    times, as they do for any unknown failure.
    """
    if isinstance(err, DestinationError):
        return err

    message = f"{type(err).__name__}: {err}"
    for error_class, kind, detail in _KINDS:
        if isinstance(err, error_class):
            return PostgreSQLOperationError(message, kind=kind, detail=_detail(err, detail))
    return PostgreSQLOperationError(message, kind=ErrorKind.TRANSIENT, detail=_detail(err, None))


def _detail(err: Exception, template: str | None) -> str | None:
    sqlstate = err.sqlstate if isinstance(err, psycopg.Error) else None
    if template is None:
        return DATABASE_ERROR_DETAIL.format(sqlstate=sqlstate) if sqlstate is not None else None
    return template.format(sqlstate=sqlstate or "unknown")
