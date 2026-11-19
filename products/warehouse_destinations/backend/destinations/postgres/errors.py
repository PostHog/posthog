"""Errors the Postgres destination raises.

Callers decide which errors not to retry by the class name, so keep the names stable
(for example `PostgreSQLConnectionError` or `MissingPrimaryKeyError`).
"""

from products.warehouse_destinations.backend.facade.contracts import DestinationConfigurationError, DestinationError


class PostgreSQLConnectionError(DestinationError):
    """The client could not connect, or an operation ran without a connection."""


class PostgreSQLConnectionConfigurationError(PostgreSQLConnectionError, DestinationConfigurationError):
    """The connection settings stop every connection attempt, so a retry cannot succeed."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"Destination configuration error. {detail}")


class PostgreSQLIntegrationNotFoundError(DestinationConfigurationError):
    """The integration that holds the connection details does not exist."""


class PostgreSQLMissingRequiredInputsError(DestinationConfigurationError):
    """The connection is missing required details, for example the host or the password."""

    def __init__(self, err_msg: str) -> None:
        super().__init__(f"The export is missing required connection inputs: {err_msg}")


class PostgreSQLIncompatibleSchemaError(DestinationConfigurationError):
    """The destination table schema does not match the schema of the data."""

    def __init__(self, err_msg: str) -> None:
        super().__init__(f"The data being exported is incompatible with the schema of the destination table: {err_msg}")


class PostgreSQLInvalidTargetError(DestinationConfigurationError):
    """The target cannot work in Postgres, for example a name that is too long or an unknown column type."""


class PostgreSQLUnrelatedTableError(DestinationConfigurationError):
    """A write would replace or reuse a table that the caller did not create."""


class MissingPrimaryKeyError(DestinationConfigurationError):
    """A merge target has no unique constraint on the merge keys."""

    def __init__(self, table: str, primary_key: tuple[str, ...]) -> None:
        super().__init__(
            f"An operation could not be completed as '{table}' is missing a primary key on {', '.join(primary_key)}"
        )


class ColumnTypeMappingError(DestinationConfigurationError, TypeError):
    """No Postgres type exists for an Arrow type under the strict type policy."""

    def __init__(self, destination: str, column: str, column_type: object) -> None:
        self.destination = destination
        self.column = column
        self.column_type = str(column_type)
        super().__init__(f"No {destination} type mapping for column '{column}' with Arrow type '{column_type}'.")


class PostgreSQLTransactionError(DestinationError):
    """A transaction failed to complete after a number of retries."""

    def __init__(self, max_attempts: int, err_msg: str) -> None:
        super().__init__(f"A transaction failed to complete after {max_attempts} attempts: {err_msg}")


class PostgreSQLMergeTimeoutError(DestinationError):
    """The merge waited on locks or hit the statement timeout after a number of attempts."""
