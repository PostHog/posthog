import re

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldFileUploadConfig,
    SourceFieldInputConfig,
    SourceFieldOauthAccountSelectConfig,
    SourceFieldOauthConfig,
    SourceFieldSelectConfig,
    SourceFieldSSHTunnelConfig,
    SourceFieldSwitchGroupConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.postgres import (
    PostgresSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source import PostgresSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

_SourceField = (
    SourceFieldInputConfig
    | SourceFieldSwitchGroupConfig
    | SourceFieldSelectConfig
    | SourceFieldOauthConfig
    | SourceFieldOauthAccountSelectConfig
    | SourceFieldFileUploadConfig
    | SourceFieldSSHTunnelConfig
)

# planetscale.com is the dashboard, never a database endpoint — Postgres hosts live on
# psdb.cloud. Pasting the dashboard address otherwise fails as an opaque connection timeout.
_PLANETSCALE_WEB_HOST_RE = re.compile(r"(^|\.)planetscale\.com$", re.IGNORECASE)

_DIRECT_HOST_EXAMPLE = "xxxxxxxxxx-useast1-1.horizon.psdb.cloud"

# PlanetScale serves Postgres on 5432 directly and on 6432 through PSBouncer. PSBouncer pools in
# transaction mode, which logical replication can't run over, so CDC needs the direct port.
_PSBOUNCER_PORT = 6432

_HOST_CAPTION = (
    "In the PlanetScale dashboard, open your database and click **Connect** to create a role and "
    "read its connection details. Use the host it shows, which looks like "
    f"`{_DIRECT_HOST_EXAMPLE}`. PlanetScale always connects over TLS, which PostHog uses by "
    "default. A read-only role is enough for syncing."
)

_PORT_CAPTION = (
    "Use `5432` for a direct connection. Port `6432` goes through PSBouncer, which works for "
    "standard syncs but not for **change data capture (CDC)**. PSBouncer pools in transaction "
    "mode, and logical replication can't run over it."
)

_USER_CAPTION = "PlanetScale usernames carry the branch id, so they look like `postgres.xxxxxxxxxx`."

_HOST_IS_DASHBOARD_ERROR = (
    "That address is the PlanetScale dashboard, not a database host. Open your database in "
    "PlanetScale, click Connect, create a role, and use the host it shows, for example "
    f"{_DIRECT_HOST_EXAMPLE}."
)

_PSBOUNCER_CDC_ERROR = (
    "Port 6432 is PlanetScale's PSBouncer endpoint, which pools connections in transaction mode "
    "and so can't carry logical replication. For change data capture, connect directly on port "
    "5432 instead."
)


def _bare_host(host: str) -> str:
    """Reduce a pasted value to a bare host: drop any path and surrounding whitespace."""
    return (host or "").strip().split("/", 1)[0]


def _is_psbouncer_port(port: int | str | None) -> bool:
    # The port survives a round trip through the source config, so it can arrive as a string.
    try:
        return int(port) == _PSBOUNCER_PORT if port is not None else False
    except ValueError:
        return False


@SourceRegistry.register
class PlanetScalePostgresSource(PostgresSource):
    """PlanetScale Postgres is stock PostgreSQL, so it reuses the Postgres driver wholesale.

    Only the connection differs: TLS is mandatory, the username carries the branch id, and there
    is no SSH tunnel to configure. PlanetScale's original Vitess databases speak MySQL instead —
    see `planetscale_mysql`.
    """

    api_docs_url = "https://planetscale.com/docs/postgres"

    def __init__(self):
        super().__init__(source_name="PlanetScale Postgres")

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PLANETSCALEPOSTGRES

    @staticmethod
    def _adjust_field(field: _SourceField) -> _SourceField:
        if not isinstance(field, SourceFieldInputConfig):
            return field
        if field.name == "connection_string":
            return field.model_copy(
                update={
                    "placeholder": f"postgresql://postgres.xxxxxxxxxx:pscale_pw_xxxxxxxx@{_DIRECT_HOST_EXAMPLE}:5432/postgres?sslmode=verify-full"
                }
            )
        if field.name == "host":
            return field.model_copy(update={"placeholder": _DIRECT_HOST_EXAMPLE, "caption": _HOST_CAPTION})
        if field.name == "port":
            return field.model_copy(update={"placeholder": "5432", "caption": _PORT_CAPTION})
        if field.name == "user":
            return field.model_copy(update={"placeholder": "postgres.xxxxxxxxxx", "caption": _USER_CAPTION})
        return field

    @property
    def get_source_config(self) -> SourceConfig:
        # PlanetScale exposes no SSH tunnel, so the inherited tunnel toggle is dropped rather
        # than shown and left unusable.
        fields = [
            self._adjust_field(field)
            for field in super().get_source_config.fields
            if not isinstance(field, SourceFieldSSHTunnelConfig)
        ]

        return SourceConfig(
            name=SchemaExternalDataSourceType.PLANET_SCALE_POSTGRES,
            category=DataWarehouseSourceCategory.DATABASES,
            keywords=["sql", "postgresql", "postgres", "planetscale"],
            label="PlanetScale Postgres",
            caption="Enter your PlanetScale Postgres credentials to pull your data into the PostHog Data warehouse.",
            iconPath="/static/services/planetscale.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/planetscale",
            fields=fields,
            releaseStatus=ReleaseStatus.ALPHA,
        )

    def validate_credentials(
        self,
        config: PostgresSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if _PLANETSCALE_WEB_HOST_RE.search(_bare_host(config.host or "")):
            return False, _HOST_IS_DASHBOARD_ERROR

        return super().validate_credentials(config, team_id, schema_name=schema_name, api_version=api_version)

    def check_cdc_prerequisites(
        self,
        config: PostgresSourceConfig,
        management_mode: str,
        tables: list[str],
        slot_name: str | None = None,
        publication_name: str | None = None,
        require_ssl: bool = True,
    ) -> list[str]:
        # PSBouncer accepts normal connections, so the generic checks would pass — but logical
        # replication doesn't work through it. Fail fast without connecting.
        if _is_psbouncer_port(config.port):
            return [_PSBOUNCER_CDC_ERROR]
        return super().check_cdc_prerequisites(
            config,
            management_mode=management_mode,
            tables=tables,
            slot_name=slot_name,
            publication_name=publication_name,
            require_ssl=require_ssl,
        )
