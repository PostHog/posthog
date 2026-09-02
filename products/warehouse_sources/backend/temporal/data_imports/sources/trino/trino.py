from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from requests.exceptions import RequestException

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import log_connection_open
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.trino import TrinoSourceConfig

if TYPE_CHECKING:
    from trino.dbapi import Connection, Cursor


TRINO_SYSTEM_SCHEMAS = ("information_schema",)
TRINO_CREDENTIALS_REQUIRE_TLS_VERIFICATION_ERROR = (
    "Turn on TLS certificate verification to use password or JWT authentication."
)
TRINO_AUTHENTICATION_ERROR = "Trino rejected the credentials. Check the username and authentication details."
TRINO_CATALOG_NOT_FOUND_ERROR = "Trino could not find that catalog. Check the catalog name and the user's permissions."
TRINO_ACCESS_DENIED_ERROR = (
    "Trino did not allow this user to read the requested data. "
    "Ask your Trino administrator for read access, then try again."
)
TRINO_ACCESS_CONTROL_UNAVAILABLE_ERROR = (
    "Trino's access control service did not answer, so Trino could not authorize the request. "
    "Try again, or ask your Trino administrator to check that service."
)
TRINO_TLS_CERTIFICATE_ERROR = (
    "PostHog could not verify the Trino server's TLS certificate. "
    "Check the certificate or turn off certificate verification."
)
TRINO_CONNECTION_ERROR = "PostHog could not connect to Trino."

# Every message `trino_error_to_message` produces for a recognized failure. The source lists them as
# its own error patterns, so the API shows the message instead of a generic one.
TRINO_KNOWN_ERROR_MESSAGES = (
    TRINO_CREDENTIALS_REQUIRE_TLS_VERIFICATION_ERROR,
    TRINO_AUTHENTICATION_ERROR,
    TRINO_CATALOG_NOT_FOUND_ERROR,
    TRINO_ACCESS_DENIED_ERROR,
    TRINO_ACCESS_CONTROL_UNAVAILABLE_ERROR,
    TRINO_TLS_CERTIFICATE_ERROR,
    TRINO_CONNECTION_ERROR,
)
POSTHOG_MANAGED_TRINO_HOSTS = frozenset(
    {
        "trino.dw.dev.postwh.com",
        "trino.dw.us.postwh.com",
    }
)


def _is_posthog_managed_trino_host(host: str) -> bool:
    return host.lower().rstrip(".") in POSTHOG_MANAGED_TRINO_HOSTS


@frozen
class TrinoColumn:
    name: str
    data_type: str
    nullable: bool


@frozen
class DiscoveredTrinoTable:
    catalog: str
    schema: str
    name: str
    columns: tuple[TrinoColumn, ...]


class TrinoSchemaDiscoveryError(Exception):
    """A failure Trino reported while PostHog listed the catalog's tables.

    The message is already worded for the person who connects the source.
    """


class TrinoConfigurationError(ValueError):
    """A connection setting Trino cannot be reached with, found before PostHog opens the connection."""


@contextmanager
def trino_failures_as_discovery_error() -> Iterator[None]:
    """Word a failed trip to Trino for the person who connects the source.

    A failure of PostHog's own code keeps its type, so error tracking still sees it.
    """
    from trino.exceptions import Error, HttpError  # noqa: PLC0415 — keeps the optional driver off startup paths

    try:
        yield
    except (Error, HttpError, RequestException, TrinoConfigurationError) as exc:
        raise TrinoSchemaDiscoveryError(trino_error_to_message(exc)) from exc


def trino_error_to_message(error: Exception) -> str:
    message = str(error).strip()
    lowered = message.lower()
    if message == TRINO_CREDENTIALS_REQUIRE_TLS_VERIFICATION_ERROR:
        return message
    # Match the driver's HTTP 401 form ("error 401: ..."), not a bare "401": a Trino query error's
    # text carries a query ID whose time part can hold "401" and would derail this classification.
    if "authentication" in lowered or "unauthorized" in lowered or "error 401" in lowered:
        return TRINO_AUTHENTICATION_ERROR
    # Trino gives permission checks to an access control plugin. That plugin can fail on its own, for
    # example when it cannot reach its policy service, which nobody can fix from PostHog.
    if "opa backend" in lowered or "access control" in lowered:
        return TRINO_ACCESS_CONTROL_UNAVAILABLE_ERROR
    if "access denied" in lowered or "permission denied" in lowered or "not authorized" in lowered:
        return TRINO_ACCESS_DENIED_ERROR
    if "catalog" in lowered and ("not found" in lowered or "does not exist" in lowered):
        return TRINO_CATALOG_NOT_FOUND_ERROR
    if "certificate" in lowered or "ssl" in lowered:
        return TRINO_TLS_CERTIFICATE_ERROR
    return message.splitlines()[0] if message else TRINO_CONNECTION_ERROR


def _authentication(config: TrinoSourceConfig) -> Any:
    selection = config.auth_type.selection
    if selection == "none":
        return None

    from trino.auth import (  # noqa: PLC0415 — keeps the optional driver off startup paths
        BasicAuthentication,
        JWTAuthentication,
    )

    if selection == "password":
        if not config.auth_type.password:
            raise TrinoConfigurationError("Password is required for password authentication.")
        return BasicAuthentication(config.auth_type.user, config.auth_type.password)
    if selection == "jwt":
        if not config.auth_type.token:
            raise TrinoConfigurationError("Token is required for JWT authentication.")
        return JWTAuthentication(config.auth_type.token)
    raise TrinoConfigurationError("Choose a supported Trino authentication type.")


@contextmanager
def connect_trino(config: TrinoSourceConfig) -> Iterator[Connection]:
    from trino.dbapi import connect  # noqa: PLC0415 — keeps the optional driver off startup paths

    if config.auth_type.selection != "none":
        if not config.use_ssl:
            raise TrinoConfigurationError("Password and JWT authentication require HTTPS.")
        if not config.verify_ssl:
            raise TrinoConfigurationError(TRINO_CREDENTIALS_REQUIRE_TLS_VERIFICATION_ERROR)

    redacted = tuple(
        value for value in (config.auth_type.password, config.auth_type.token) if isinstance(value, str) and value
    )
    session = make_tracked_session(redact_values=redacted, allow_redirects=False)
    if _is_posthog_managed_trino_host(config.host) and config.port == 443 and config.use_ssl and config.verify_ssl:
        session.trust_env = False
    session.verify = config.verify_ssl
    log_connection_open(db_host=config.host, via="trino_https" if config.use_ssl else "trino_http")
    connection: Connection | None = None
    try:
        connection = connect(
            host=config.host,
            port=config.port,
            user=config.auth_type.user,
            catalog=config.catalog,
            schema=(config.schema or None),
            http_scheme="https" if config.use_ssl else "http",
            auth=_authentication(config),
            http_session=session,
            request_timeout=60,
            verify=config.verify_ssl,
        )
        yield connection
    finally:
        try:
            if connection is not None:
                connection.close()
        finally:
            session.close()


def discover_trino_schemas(
    cursor: Cursor, config: TrinoSourceConfig, names: list[str] | None = None
) -> list[DiscoveredTrinoTable]:
    query = (
        "SELECT table_schema, table_name, column_name, data_type, is_nullable "
        f'FROM "{config.catalog.replace(chr(34), chr(34) * 2)}".information_schema.columns '
        "WHERE table_schema <> 'information_schema'"
    )
    parameters: list[object] = []
    if config.schema:
        query += " AND table_schema = ?"
        parameters.append(config.schema)
    query += " ORDER BY table_schema, table_name, ordinal_position"
    cursor.execute(query, parameters)

    requested = set(names) if names is not None else None
    tables: dict[tuple[str, str], list[TrinoColumn]] = {}
    for schema_name, table_name, column_name, data_type, is_nullable in cursor.fetchall():
        display_name = str(table_name) if config.schema else f"{schema_name}.{table_name}"
        if requested is not None and display_name not in requested:
            continue
        tables.setdefault((str(schema_name), str(table_name)), []).append(
            TrinoColumn(
                name=str(column_name),
                data_type=str(data_type),
                nullable=str(is_nullable).upper() == "YES",
            )
        )
    return [
        DiscoveredTrinoTable(
            catalog=config.catalog,
            schema=schema_name,
            name=table_name,
            columns=tuple(columns),
        )
        for (schema_name, table_name), columns in tables.items()
    ]
