from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

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


def trino_error_to_message(error: Exception) -> str:
    message = str(error).strip()
    lowered = message.lower()
    if message == TRINO_CREDENTIALS_REQUIRE_TLS_VERIFICATION_ERROR:
        return message
    if "authentication" in lowered or "unauthorized" in lowered or "401" in lowered:
        return "Trino rejected the credentials. Check the username and authentication details."
    if "catalog" in lowered and ("not found" in lowered or "does not exist" in lowered):
        return "Trino could not find that catalog. Check the catalog name and the user's permissions."
    if "certificate" in lowered or "ssl" in lowered:
        return "PostHog could not verify the Trino server's TLS certificate. Check the certificate or turn off certificate verification."
    return message.splitlines()[0] if message else "PostHog could not connect to Trino."


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
            raise ValueError("Password is required for password authentication.")
        return BasicAuthentication(config.auth_type.user, config.auth_type.password)
    if selection == "jwt":
        if not config.auth_type.token:
            raise ValueError("Token is required for JWT authentication.")
        return JWTAuthentication(config.auth_type.token)
    raise ValueError("Choose a supported Trino authentication type.")


@contextmanager
def connect_trino(config: TrinoSourceConfig) -> Iterator[Connection]:
    from trino.dbapi import connect  # noqa: PLC0415 — keeps the optional driver off startup paths

    if config.auth_type.selection != "none":
        if not config.use_ssl:
            raise ValueError("Password and JWT authentication require HTTPS.")
        if not config.verify_ssl:
            raise ValueError(TRINO_CREDENTIALS_REQUIRE_TLS_VERIFICATION_ERROR)

    redacted = tuple(
        value for value in (config.auth_type.password, config.auth_type.token) if isinstance(value, str) and value
    )
    session = make_tracked_session(redact_values=redacted, allow_redirects=False)
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
