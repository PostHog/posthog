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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.postgres import (
    PostgresSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source import (
    _HOST_UNREACHABLE_ERROR,
    _INVALID_USER_OR_PASSWORD,
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
# connection failures. Standard syncs need the connection pooler host instead. The `ref`
# group is the project ref, which is also the suffix of the pooler username (`postgres.<ref>`).
_SUPABASE_DIRECT_HOST_RE = re.compile(r"^db\.(?P<ref>[a-z0-9]+)\.supabase\.co$", re.IGNORECASE)

# The Supabase dashboard shows `https://<ref>.supabase.co` as the "Project URL" — that's the
# REST/API endpoint, not a Postgres host. Pasting it (often with the scheme) into the host field
# just yields an opaque DNS failure, so detect it and point users at the actual database host.
_SUPABASE_PROJECT_HOST_RE = re.compile(r"^(?P<ref>[a-z0-9]+)\.supabase\.co$", re.IGNORECASE)

# Supabase's shared regional pooler (`aws-0-<region>.pooler.supabase.com`) can't identify the
# project from SNI, so its username must embed the project ref (`postgres.<project-ref>`). A plain
# `postgres` username is the common mistake, and the pooler then rejects it as a bad password.
_SUPABASE_POOLER_HOST_RE = re.compile(r"\.pooler\.supabase\.com$", re.IGNORECASE)


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


# A rejected password on the pooler maps to a bare "Invalid user or password" in the shared Postgres
# error map, which never mentions the pooler-username requirement. Name it here so pooler users learn
# that a plain `postgres` username is the usual cause.
_SUPABASE_POOLER_INVALID_CREDENTIALS = (
    "The Supabase pooler rejected the username or password. On the pooler the username must be "
    "postgres.<project-ref> (not plain postgres) — check the username, then the password, and try "
    "again."
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
        is_pooler_host = bool(_SUPABASE_POOLER_HOST_RE.search(bare_host))
        success, error = super().validate_credentials(config, team_id, schema_name=schema_name)
        if not success and is_direct_host and error == _HOST_UNREACHABLE_ERROR:
            return False, _SUPABASE_DIRECT_HOST_IPV4_HINT
        # On the pooler a bad password is usually a plain `postgres` username instead of
        # `postgres.<project-ref>`, but the shared Postgres map only says the password is wrong.
        if not success and is_pooler_host and error == _INVALID_USER_OR_PASSWORD:
            return False, _SUPABASE_POOLER_INVALID_CREDENTIALS
        return success, error

    def validate_credentials_for_access_method(
        self,
        config: PostgresSourceConfig,
        team_id: int,
        access_method: str,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
        cdc_enabled: bool = False,
    ) -> tuple[bool, str | None]:
        # A standard sync can never use the IPv6-only direct host, so fail it instantly with the
        # pooler host and username spelled out — no need to wait for the connection to time out.
        # CDC does need the direct host (plus the IPv4 add-on), so leave that path to the real
        # connection attempt, which `validate_credentials` still handles.
        if not cdc_enabled:
            direct_host = _SUPABASE_DIRECT_HOST_RE.match(_strip_host_scheme(config.host or ""))
            if direct_host:
                # Project refs are lowercase and the pooler username is case-sensitive, so lowercase
                # the ref even when the user typed the host in caps.
                ref = direct_host.group("ref").lower()
                return False, (
                    f"'db.{ref}.supabase.co' is the Supabase direct host. It's IPv6-only, so PostHog can't "
                    "reach it over IPv4. For standard syncs use the Session pooler host "
                    f"(aws-0-<region>.pooler.supabase.com) with username postgres.{ref}. For change data "
                    "capture, keep the direct host and enable Supabase's IPv4 add-on (Project settings → Add-ons)."
                )
        return self.validate_credentials(config, team_id, schema_name=schema_name, api_version=api_version)
