import re
from typing import Optional

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    rank_incremental_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.postgres import (
    PostgresSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source import (
    _HOST_UNREACHABLE_ERROR,
    PostgresSource,
)
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

# Supabase's direct connection host (`db.<ref>.supabase.co`) is IPv6-only and so is
# unreachable from PostHog's IPv4 egress — by far the biggest cause of Supabase
# connection failures. Users need the connection pooler host instead.
_SUPABASE_DIRECT_HOST_RE = re.compile(r"^db\.[a-z0-9]+\.supabase\.co$", re.IGNORECASE)

# The Supabase dashboard shows `https://<ref>.supabase.co` as the "Project URL" — that's the
# REST/API endpoint, not a Postgres host. Pasting it (often with the scheme) into the host field
# just yields an opaque DNS failure, so detect it and point users at the actual database host.
_SUPABASE_PROJECT_HOST_RE = re.compile(r"^(?P<ref>[a-z0-9]+)\.supabase\.co$", re.IGNORECASE)


def _strip_host_scheme(host: str) -> str:
    """Reduce a pasted value to a bare host: drop any URL scheme, path, and surrounding whitespace."""
    stripped = re.sub(r"^[a-z][a-z0-9+.-]*://", "", (host or "").strip(), flags=re.IGNORECASE)
    return stripped.split("/", 1)[0]


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

# Supabase Realtime stores messages in daily partitions of its internal `realtime.messages` table
# named `realtime.messages_YYYY_MM_DD`, and its retention job drops the old partitions. A sync that
# targets one of these dated partitions fails with `relation "realtime.messages_..." does not exist`
# once that day is dropped. Match the stable partition-name prefix (never the volatile date). The
# inherited generic `"does not exist"` already classifies this non-retryable; this entry only adds an
# actionable message, so it must precede the generic key in `get_non_retryable_errors` (first match
# wins) with a non-None value.
_SUPABASE_REALTIME_PARTITION_ERROR = "realtime.messages_"
_SUPABASE_REALTIME_PARTITION_MESSAGE = (
    "Supabase creates a new realtime.messages partition each day and drops old ones automatically, "
    "so the dated partition this sync read no longer exists. These partitions are temporary and "
    "aren't meant to be synced. Remove this table from the source's selected tables, then re-enable "
    "the sync."
)

# Supabase Vault's schema: its `decrypted_secrets` view decrypts every stored secret on read,
# so sync-enabling it by default would copy a secrets vault into the warehouse.
_VAULT_SCHEMA = "vault"


@SourceRegistry.register
class SupabaseSource(PostgresSource):
    def __init__(self):
        super().__init__(source_name="Supabase")

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SUPABASE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            _SUPABASE_REALTIME_PARTITION_ERROR: _SUPABASE_REALTIME_PARTITION_MESSAGE,
            **super().get_non_retryable_errors(),
        }

    def get_schemas(
        self,
        config: PostgresSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
        require_ssl: bool = False,
    ) -> list[SourceSchema]:
        schemas = super().get_schemas(
            config,
            team_id,
            with_counts=with_counts,
            names=names,
            force_refresh=force_refresh,
            api_version=api_version,
            require_ssl=require_ssl,
        )

        # Vault tables must never be sync-enabled by default. They stay listed rather than
        # filtered because scheduled discovery reconciles stored rows against this listing
        # and would disable a vault sync a user deliberately opted into; default-off is
        # honored by the picker, one-shot setup, and auto-sync of newly discovered schemas.
        for schema in schemas:
            if schema.source_schema == _VAULT_SCHEMA:
                schema.should_sync_default = False

        # Supabase tables carry arbitrary user columns, so the first discovered candidate
        # (column ordinal order) is often a value that never changes on update. Rank
        # update-tracking columns first so surfaces defaulting to the leading candidate
        # propose a cursor that actually advances.
        for schema in schemas:
            schema.incremental_fields = rank_incremental_fields(schema.incremental_fields)

        return schemas

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
            keywords=["sql", "postgresql", "postgres"],
            featured=True,
            iconPath="/static/services/supabase.png",
            caption="Enter your Supabase credentials to automatically pull your data into the PostHog Data warehouse",
            docsUrl="https://posthog.com/tutorials/supabase-query",
            fields=fields,
            releaseStatus=ReleaseStatus.GA,
        )

    def validate_credentials(
        self,
        config: PostgresSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        bare_host = _strip_host_scheme(config.host or "")
        project_host = _SUPABASE_PROJECT_HOST_RE.match(bare_host)
        if project_host:
            # Project refs are lowercase, and the pooler username (postgres.<ref>) is
            # case-sensitive — canonicalize so the suggested values are copy-pasteable.
            ref = project_host.group("ref").lower()
            return False, (
                f"'{bare_host}' looks like your Supabase project URL, not a database "
                "host. For standard syncs use the Session pooler host (aws-0-<region>.pooler.supabase.com) with "
                f"username postgres.{ref}; for change data capture use the direct host db.{ref}.supabase.co and "
                "enable Supabase's IPv4 add-on."
            )

        # The direct host (IPv6-only by default) is the only host that supports logical
        # replication, so CDC users need it. We let the real connection attempt decide
        # reachability — it succeeds when the IPv4 add-on is enabled. Only the unreachable
        # failure is the IPv4 case, so swap in Supabase-specific pooler guidance there; other
        # failures (bad password, missing database, SSL) already have clear messages, and
        # blaming them on IPv4 would misdirect the user.
        is_direct_host = bool(_SUPABASE_DIRECT_HOST_RE.match((config.host or "").strip()))
        success, error = super().validate_credentials(config, team_id, schema_name=schema_name)
        if not success and is_direct_host and error == _HOST_UNREACHABLE_ERROR:
            return False, _SUPABASE_DIRECT_HOST_IPV4_HINT
        return success, error
