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

_NEON_POOLED_HOST_CDC_ERROR = (
    "This is Neon's pooled endpoint, which doesn't support logical replication. For CDC, use the "
    "direct host instead — remove the '-pooler' suffix (e.g. "
    "ep-cool-darkness-123456.us-east-2.aws.neon.tech) — and make sure logical replication is "
    "enabled in your Neon project settings."
)


def _is_neon_pooled_host(host: str) -> bool:
    bare = (host or "").strip().lower()
    return bare.endswith(".neon.tech") and bare.split(".", 1)[0].endswith("-pooler")


_NEON_HOST_CAPTION = (
    "In the Neon Console, open your project and click **Connect** to see your connection "
    "details. Use the direct host, e.g. `ep-cool-darkness-123456.us-east-2.aws.neon.tech` — "
    "not the pooled host (the one with `-pooler`). Pooled connections work for standard "
    "syncs, but **change data capture (CDC)** requires the direct host, and you must enable "
    "**logical replication** in your Neon project settings first. Neon requires SSL, which "
    "PostHog uses by default."
)


@SourceRegistry.register
class NeonSource(PostgresSource):
    def __init__(self):
        super().__init__(source_name="Neon")

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NEON

    @staticmethod
    def _adjust_field(field: _SourceField) -> _SourceField:
        if isinstance(field, SourceFieldInputConfig):
            if field.name == "connection_string":
                return field.model_copy(
                    update={
                        "placeholder": "postgresql://neondb_owner:password@ep-cool-darkness-123456.us-east-2.aws.neon.tech/neondb?sslmode=require"
                    }
                )
            if field.name == "host":
                return field.model_copy(
                    update={
                        "placeholder": "ep-cool-darkness-123456.us-east-2.aws.neon.tech",
                        "caption": _NEON_HOST_CAPTION,
                    }
                )
            if field.name == "database":
                return field.model_copy(update={"placeholder": "neondb"})
            if field.name == "user":
                return field.model_copy(update={"placeholder": "neondb_owner"})
        return field

    @property
    def get_source_config(self) -> SourceConfig:
        fields = [self._adjust_field(field) for field in super().get_source_config.fields]

        return SourceConfig(
            name=SchemaExternalDataSourceType.NEON,
            category=DataWarehouseSourceCategory.DATABASES,
            keywords=["serverless postgres", "postgresql"],
            iconPath="/static/services/neon.png",
            caption="Enter your Neon credentials to automatically pull your data into the PostHog Data warehouse",
            docsUrl="https://posthog.com/docs/cdp/sources/neon",
            fields=fields,
            releaseStatus=ReleaseStatus.ALPHA,
        )

    def check_cdc_prerequisites(
        self,
        config: PostgresSourceConfig,
        management_mode: str,
        tables: list[str],
        slot_name: str | None = None,
        publication_name: str | None = None,
        require_ssl: bool = True,
    ) -> list[str]:
        # The pooled endpoint accepts normal connections, so the generic checks would pass —
        # but logical replication doesn't work through it. Fail fast without connecting.
        if _is_neon_pooled_host(config.host or ""):
            return [_NEON_POOLED_HOST_CDC_ERROR]
        return super().check_cdc_prerequisites(
            config,
            management_mode=management_mode,
            tables=tables,
            slot_name=slot_name,
            publication_name=publication_name,
            require_ssl=require_ssl,
        )
