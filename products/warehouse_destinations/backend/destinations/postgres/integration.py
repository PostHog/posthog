"""Find the client settings of a Postgres destination from its `PostgresDestinationConfig`.

`database` names the database in both auth methods. With the `integration` auth method, the
host, port, user, password and TLS settings come from the integration. With `credentials`, they
come from the config itself. `spec.py` declares the fields.
"""

import typing
import pathlib
import functools
from dataclasses import field

import certifi
import psycopg

from posthog.dataclasses import frozen
from posthog.integrations import IntegrationManager, IntegrationNotFound
from posthog.models.integration import MISSING_CERT_PATH, TLS, Authority, Credentials, PostgreSQLIntegration

from products.warehouse_destinations.backend.destinations.postgres.errors import (
    PostgreSQLIntegrationNotFoundError,
    PostgreSQLMissingRequiredInputsError,
)
from products.warehouse_destinations.backend.facade.configs.postgres import (
    PostgresAuthMethodConfig,
    PostgresDestinationConfig,
)
from products.warehouse_destinations.backend.facade.contracts import (
    DestinationConfigurationError,
    DestinationConnection,
)

# An integration can still hold "prefer". Typed-in connection details cannot, because "prefer"
# falls back to a connection without TLS and so can send the password in clear text.
SSLMode = typing.Literal["prefer", "require", "verify-ca", "verify-full"]
InlineSSLMode = typing.Literal["require", "verify-ca", "verify-full"]


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
    """Connection details typed into the config, for the `credentials` auth method."""

    def __init__(self, auth: PostgresAuthMethodConfig) -> None:
        self._auth = auth

    def credentials(self) -> Credentials:
        # The config class requires these for this auth method. The checks keep a config that
        # someone changed after it was built from reaching the driver.
        if self._auth.user is None or self._auth.password is None:
            raise ValueError("Missing required inputs")
        return Credentials(self._auth.user, self._auth.password)

    def authority(self) -> Authority:
        if self._auth.host is None:
            raise ValueError("Missing required inputs")
        return Authority(self._auth.host, self._auth.port)

    def tls(self) -> TLS:
        return inline_tls(self._auth.ssl_mode)


# libpq reads `sslrootcert=system` as "use the system trust store" from version 16 on.
_SYSTEM_ROOT_CERT_MIN_LIBPQ_VERSION = 160000


def inline_tls(ssl_mode: InlineSSLMode) -> TLS:
    """The TLS settings for connection details typed into the config.

    A verify mode checks the server certificate against the system trust store. `require`
    keeps the default root certificate path, which does not exist, so libpq encrypts without a
    check and never reads a root certificate that happens to sit in its default path.
    """
    if ssl_mode == "require":
        return TLS(ssl_mode=ssl_mode)
    if psycopg.pq.version() >= _SYSTEM_ROOT_CERT_MIN_LIBPQ_VERSION:
        return TLS(ssl_mode=ssl_mode, ssl_root_cert="system")
    # An older libpq takes a root certificate file. The client writes this text to one.
    return TLS(ssl_mode=ssl_mode, ssl_root_cert=_certifi_bundle())


@functools.cache
def _certifi_bundle() -> str:
    return pathlib.Path(certifi.where()).read_text()


async def _get_postgresql_integration(team_id: int, integration_id: int | None) -> PostgreSQLIntegration:
    if integration_id is None:
        raise PostgreSQLMissingRequiredInputsError("Missing required inputs")

    try:
        integration = await IntegrationManager.postgresql.credentials.aget(team_id, integration_id)
    except IntegrationNotFound:
        raise PostgreSQLIntegrationNotFoundError(
            f"PostgreSQL integration with id '{integration_id}' not found",
            detail="The destination's connection details no longer exist. Connect the destination again.",
        ) from None
    return PostgreSQLIntegration(integration)


def _postgres_config(connection: DestinationConnection) -> PostgresDestinationConfig:
    if not isinstance(connection.config, PostgresDestinationConfig):
        raise DestinationConfigurationError(
            f"The Postgres destination needs a PostgresDestinationConfig, got {type(connection.config).__name__}"
        )
    return connection.config


async def resolve_client_settings(connection: DestinationConnection) -> PostgresClientSettings:
    """Read the settings from the integration or from the config, as its auth method says."""
    config = _postgres_config(connection)
    auth = config.auth_method

    inputs: _ClientInputs
    if auth.selection == "integration":
        inputs = await _get_postgresql_integration(connection.team_id, auth.integration_id)
    else:
        inputs = _InlineInputs(auth)

    try:
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
        database=config.database,
        ssl_mode=tls.ssl_mode,
        ssl_root_cert=tls.ssl_root_cert,
    )
