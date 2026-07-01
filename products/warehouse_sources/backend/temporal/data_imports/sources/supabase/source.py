import re
from typing import Optional

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldFileUploadConfig,
    SourceFieldInputConfig,
    SourceFieldOauthConfig,
    SourceFieldSelectConfig,
    SourceFieldSSHTunnelConfig,
    SourceFieldSwitchGroupConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PostgresSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source import PostgresSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

_SourceField = (
    SourceFieldInputConfig
    | SourceFieldSwitchGroupConfig
    | SourceFieldSelectConfig
    | SourceFieldOauthConfig
    | SourceFieldFileUploadConfig
    | SourceFieldSSHTunnelConfig
)

# Supabase's direct connection host (`db.<ref>.supabase.co`) is IPv6-only and so is
# unreachable from PostHog's IPv4 egress — by far the biggest cause of Supabase
# connection failures. Users need the connection pooler host instead.
_SUPABASE_DIRECT_HOST_RE = re.compile(r"^db\.[a-z0-9]+\.supabase\.co$", re.IGNORECASE)

_SUPABASE_POOLER_HOST_CAPTION = (
    "To get your connection string, click **Connect** in the top bar of your Supabase "
    "dashboard, open the **Direct** tab, and pick **Session pooler** or **Direct "
    "connection** — the URL is shown at the bottom. For standard syncs use the "
    "**Session pooler** host, e.g. `aws-0-<region>.pooler.supabase.com`, with username "
    "`postgres.<project-ref>` — the direct host `db.<ref>.supabase.co` is IPv6-only. "
    "For **change data capture (CDC)** you must use **Direct connection** instead and "
    "enable Supabase's **IPv4 add-on**, because logical replication doesn't work through "
    "the pooler."
)

_SUPABASE_DIRECT_HOST_IPV4_HINT = (
    "Couldn't reach the Supabase direct host (db.<ref>.supabase.co). It's IPv6-only unless you "
    "enable Supabase's IPv4 add-on (Project settings → Add-ons), which is required for change "
    "data capture. For standard (non-CDC) syncs, use the Session pooler host instead "
    "(aws-0-<region>.pooler.supabase.com) with username postgres.<project-ref>."
)


@SourceRegistry.register
class SupabaseSource(PostgresSource):
    def __init__(self):
        super().__init__(source_name="Supabase")

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SUPABASE

    @staticmethod
    def _adjust_field(field: _SourceField) -> _SourceField:
        if isinstance(field, SourceFieldInputConfig) and field.name == "host":
            return field.model_copy(
                update={
                    "placeholder": "aws-0-us-east-1.pooler.supabase.com",
                    "caption": _SUPABASE_POOLER_HOST_CAPTION,
                }
            )
        return field

    @property
    def get_source_config(self) -> SourceConfig:
        fields = [self._adjust_field(field) for field in super().get_source_config.fields]

        return SourceConfig(
            name=SchemaExternalDataSourceType.SUPABASE,
            category=DataWarehouseSourceCategory.DATABASES,
            featured=True,
            iconPath="/static/services/supabase.png",
            caption="Enter your Supabase credentials to automatically pull your data into the PostHog Data warehouse",
            docsUrl="https://posthog.com/tutorials/supabase-query",
            fields=fields,
            releaseStatus=ReleaseStatus.GA,
        )

    def validate_credentials(
        self, config: PostgresSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The direct host (IPv6-only by default) is the only host that supports logical
        # replication, so CDC users need it. We let the real connection attempt decide
        # reachability — it succeeds when the IPv4 add-on is enabled — and only swap in a
        # clearer message when it fails, since the generic Postgres error is opaque.
        is_direct_host = bool(_SUPABASE_DIRECT_HOST_RE.match((config.host or "").strip()))
        success, error = super().validate_credentials(config, team_id, schema_name=schema_name)
        if not success and is_direct_host:
            return False, _SUPABASE_DIRECT_HOST_IPV4_HINT
        return success, error
