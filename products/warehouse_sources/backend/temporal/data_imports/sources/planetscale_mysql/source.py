import re
from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.exceptions_capture import capture_exception

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mysql import MySQLSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.source import MySQLSource
from products.warehouse_sources.backend.temporal.data_imports.sources.planetscale_mysql.planetscale_mysql import (
    PlanetScaleMySQLImplementation,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_PLANETSCALE_MYSQL_IMPLEMENTATION = PlanetScaleMySQLImplementation()

# planetscale.com is the dashboard, never a database endpoint — branch connect hosts live on
# psdb.cloud. Pasting the dashboard address otherwise fails as an opaque connection timeout.
_PLANETSCALE_WEB_HOST_RE = re.compile(r"(^|\.)planetscale\.com$", re.IGNORECASE)

_CONNECT_HOST_EXAMPLE = "aws.connect.psdb.cloud"

_HOST_CAPTION = (
    "In the PlanetScale dashboard, open your database, pick the branch, and click **Connect**. "
    "Create a password there and copy the host, username, and password it shows. The host looks "
    f"like `{_CONNECT_HOST_EXAMPLE}`. PlanetScale always connects over TLS, which PostHog uses by "
    "default. A read-only password is enough for syncing."
)

_HOST_IS_URL_ERROR = (
    "Enter just the hostname in the host field, for example "
    f"{_CONNECT_HOST_EXAMPLE}. Remove any scheme, username, password, port, or path."
)

_HOST_IS_DASHBOARD_ERROR = (
    "That address is the PlanetScale dashboard, not a database host. Open your database in "
    "PlanetScale, click Connect, create a password, and use the host it shows, for example "
    f"{_CONNECT_HOST_EXAMPLE}."
)

_HOST_NOT_RESOLVED_ERROR = (
    "Could not resolve that host. Use the host shown under Connect in your PlanetScale database, "
    f"for example {_CONNECT_HOST_EXAMPLE}."
)

_GENERIC_CONNECTION_ERROR = "Could not connect to PlanetScale MySQL. Please check all connection details are valid."

# `get_schemas` already retried a transient connect-time drop in-process (`_connect_with_transient_retry`
# in mysql.py) before this exhausted every attempt, so the sync path treats the same message as benign via
# `get_retryable_errors` and never reports it. Mirror that here so a brief blip surfaced during interactive
# validation doesn't get captured as an unexpected bug.
_TRANSIENT_CONNECTION_ERROR = (
    "Lost the connection to PlanetScale while checking your credentials. This is usually a brief network "
    "blip rather than a configuration problem. Please try again."
)

# Create-time refinement of pymysql's catch-all connect error (2003), which collapses a bad host,
# a closed port, and a firewall drop into one message. Mirrors the MySQL source's handling with
# PlanetScale's own guidance. Kept out of `get_non_retryable_errors`, which the sync path also
# consults for retry classification.
_VALIDATE_CONNECTION_HINTS: list[tuple[str, str]] = [
    ("Name or service not known", _HOST_NOT_RESOLVED_ERROR),
    ("nodename nor servname provided", _HOST_NOT_RESOLVED_ERROR),
    (
        "Connection refused",
        "Could not connect on that host and port. PlanetScale accepts MySQL connections on port "
        "3306 at the host shown under Connect in your database.",
    ),
    (
        "timed out",
        "The connection timed out. Check that the branch is awake in PlanetScale and that the host "
        "and port are correct.",
    ),
    (
        "Unknown database",
        "That database does not exist on this PlanetScale branch. Check the database name is correct.",
    ),
]

_TLS_HANDSHAKE_ERROR = (
    "We couldn't open a TLS connection to PlanetScale. Check that the host is the branch connect "
    f"host, for example {_CONNECT_HOST_EXAMPLE}, and that the port is 3306."
)


def _bare_host(host: str) -> str:
    """Reduce a pasted value to a bare host: drop any path and surrounding whitespace."""
    return (host or "").strip().split("/", 1)[0]


@SourceRegistry.register
class PlanetScaleMySQLSource(MySQLSource):
    """PlanetScale's Vitess databases speak the MySQL wire protocol, so this reuses the MySQL
    driver wholesale.

    Only the connection differs: TLS is mandatory, credentials are per-branch, and there is no
    SSH tunnel to configure. PlanetScale's Postgres databases are a separate product on a
    different wire protocol — see `planetscale_postgres`.
    """

    api_docs_url = "https://planetscale.com/docs"

    @property
    def get_implementation(self) -> PlanetScaleMySQLImplementation:
        return _PLANETSCALE_MYSQL_IMPLEMENTATION

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PLANETSCALEMYSQL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PLANET_SCALE_MY_SQL,
            category=DataWarehouseSourceCategory.DATABASES,
            keywords=["sql", "mysql", "vitess", "planetscale"],
            label="PlanetScale MySQL",
            caption="Enter your PlanetScale MySQL branch credentials to pull your data into the PostHog Data warehouse.",
            iconPath="/static/services/planetscale.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/planetscale",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="host",
                        label="Host",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder=_CONNECT_HOST_EXAMPLE,
                        caption=_HOST_CAPTION,
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="port",
                        label="Port",
                        type=SourceFieldInputConfigType.NUMBER,
                        required=True,
                        placeholder="3306",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="database",
                        label="Database",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="my-database",
                        caption="The PlanetScale database name, shown in the connection details.",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="user",
                        label="Username",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="password",
                        label="Password",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="schema",
                        label="Schema",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="Leave blank to include every database on the branch",
                        secret=False,
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        errors = super().get_non_retryable_errors()
        # The inherited message tells the user to turn SSL off, which PlanetScale doesn't allow.
        errors["[SSL: WRONG_VERSION_NUMBER]"] = _TLS_HANDSHAKE_ERROR
        return errors

    def validate_credentials(
        self,
        config: MySQLSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        host = config.host or ""
        if "://" in host:
            return False, _HOST_IS_URL_ERROR

        if _PLANETSCALE_WEB_HOST_RE.search(_bare_host(host)):
            return False, _HOST_IS_DASHBOARD_ERROR

        valid_host, host_errors = self.is_database_host_valid(host, team_id, using_ssh_tunnel=False)
        if not valid_host:
            return valid_host, host_errors

        try:
            self.get_schemas(config, team_id, api_version=api_version)
        except Exception as e:
            # Failures we already classify as non-retryable during sync are expected user or
            # upstream errors, not bugs on our side, so they're reported without capturing.
            error_msg = " ".join(str(arg) for arg in e.args) if e.args else str(e)
            for hint_pattern, hint_message in _VALIDATE_CONNECTION_HINTS:
                if hint_pattern in error_msg:
                    return False, hint_message
            for pattern, friendly_error in self.get_non_retryable_errors().items():
                if pattern in error_msg:
                    return False, friendly_error or _GENERIC_CONNECTION_ERROR
            for pattern in self.get_retryable_errors():
                if pattern in error_msg:
                    return False, _TRANSIENT_CONNECTION_ERROR

            capture_exception(e)
            return False, _GENERIC_CONNECTION_ERROR

        return True, None
