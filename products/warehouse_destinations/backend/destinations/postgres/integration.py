"""Find the connection settings of a Postgres destination.

`DestinationConnection.config` keys this destination reads:

- `database` (required): the database to connect to. Target namespaces are schemas in it.
- `host` and `port`: required when the connection has no integration.
- `ssl_mode`: the TLS mode of a connection without an integration. One of `prefer`, `require`,
  `verify-ca` and `verify-full`; the default is `require`. An integration sets its own mode.
"""

import typing
from dataclasses import field

from posthog.dataclasses import frozen
from posthog.integrations import IntegrationManager, IntegrationNotFound
from posthog.models.integration import MISSING_CERT_PATH, TLS, Authority, Credentials, PostgreSQLIntegration

from products.warehouse_destinations.backend.destinations.postgres.errors import (
    PostgreSQLIntegrationNotFoundError,
    PostgreSQLMissingRequiredInputsError,
)
from products.warehouse_destinations.backend.facade.contracts import DestinationConnection

SSLMode = typing.Literal["prefer", "require", "verify-ca", "verify-full"]
DEFAULT_SSL_MODE: SSLMode = "require"


@frozen
class PostgresClientSettings:
    user: str
    password: str = field(repr=False)
    host: str
    port: int
    database: str
    ssl_mode: SSLMode
    ssl_root_cert: str = MISSING_CERT_PATH


class _ClientInputs(typing.Protocol):
    def credentials(self) -> Credentials: ...

    def authority(self) -> Authority: ...

    def tls(self) -> TLS: ...


class _InlineInputs:
    """Connection details stored inline on the connection, used when there is no integration."""

    def __init__(self, connection: DestinationConnection) -> None:
        self._connection = connection

    def credentials(self) -> Credentials:
        user = self._connection.credentials.get("user")
        password = self._connection.credentials.get("password")
        if user is None or password is None:
            raise ValueError("Missing required inputs")
        return Credentials(user, password)

    def authority(self) -> Authority:
        host = self._connection.config.get("host")
        port = self._connection.config.get("port")
        if host is None or port is None:
            raise ValueError("Missing required inputs")
        return Authority(host, int(port))

    def tls(self) -> TLS:
        ssl_mode = self._connection.config.get("ssl_mode", DEFAULT_SSL_MODE)
        if ssl_mode not in typing.get_args(SSLMode):
            raise ValueError(f"Unsupported ssl_mode '{ssl_mode}'")
        return TLS(ssl_mode=ssl_mode)


async def _get_postgresql_integration(connection: DestinationConnection) -> PostgreSQLIntegration | None:
    if connection.integration_id is None:
        return None

    try:
        integration = await IntegrationManager.postgresql.credentials.aget(
            connection.team_id, connection.integration_id
        )
    except IntegrationNotFound:
        raise PostgreSQLIntegrationNotFoundError(
            f"PostgreSQL integration with id '{connection.integration_id}' not found",
            detail="The destination's connection details no longer exist. Connect the destination again.",
        ) from None
    return PostgreSQLIntegration(integration)


async def resolve_client_settings(connection: DestinationConnection) -> PostgresClientSettings:
    """Read the settings from the integration, or from the connection when it has no integration.

    `connection.config["database"]` names the database in both cases.
    """
    inputs: _ClientInputs = await _get_postgresql_integration(connection) or _InlineInputs(connection)

    database = connection.config.get("database")
    try:
        if not database:
            raise ValueError("Missing required inputs")
        credentials = inputs.credentials()
        authority = inputs.authority()
        tls = inputs.tls()
    except (KeyError, TypeError, ValueError) as err:
        raise PostgreSQLMissingRequiredInputsError(str(err)) from err

    return PostgresClientSettings(
        user=credentials.user,
        password=credentials.password,
        host=authority.host,
        port=authority.port,
        database=database,
        ssl_mode=tls.ssl_mode,
        ssl_root_cert=tls.ssl_root_cert,
    )
