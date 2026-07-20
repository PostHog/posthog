from typing import Optional, cast
from urllib.parse import urlsplit

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GitguardianSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gitguardian.gitguardian import (
    GitGuardianResumeConfig,
    check_endpoint_access,
    gitguardian_source,
    resolve_base_url,
    validate_base_url,
    validate_credentials as validate_gitguardian_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gitguardian.settings import (
    ENDPOINTS,
    GITGUARDIAN_ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GitguardianSource(ResumableSource[GitguardianSourceConfig, GitGuardianResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GITGUARDIAN

    @property
    def connection_host_fields(self) -> list[str]:
        # The API token is sent to whatever `base_url` points at, so retargeting it must re-require
        # the secret — otherwise the preserved token could be exfiltrated to an attacker-controlled host.
        return ["base_url"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GITGUARDIAN,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="GitGuardian",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter a GitGuardian API token to sync your secret incidents, occurrences, monitored sources, honeytokens, members, and teams into the PostHog Data warehouse.

Create a service account token (recommended for unattended syncs) or a personal access token in your [GitGuardian API settings](https://dashboard.gitguardian.com/api). Grant the read scopes for the tables you want to sync: `incidents:read`, `sources:read`, `honeytokens:read`, `members:read`, and `teams:read`. Reading incidents requires a token with at least the Manager access level.

Workspaces on the EU instance should set the API URL to `https://api.eu1.gitguardian.com`; self-hosted instances should enter their own API URL.
""",
            iconPath="/static/services/gitguardian.png",
            docsUrl="https://posthog.com/docs/cdp/sources/gitguardian",
            keywords=["secrets", "secret scanning", "code security", "honeytoken"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="gg_sat_... or gg_pat_...",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="base_url",
                        label="API URL (EU or self-hosted only)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="https://api.gitguardian.com",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.gitguardian.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked token surfaces as a requests HTTPError when `_fetch_page` calls
            # `raise_for_status()`. Retrying can never satisfy a credential problem, so stop the
            # sync. The base host varies for EU/self-hosted instances, so match the stable status
            # text only.
            "401 Client Error": "Your GitGuardian API token is invalid or has been revoked. Create a new token in your GitGuardian API settings, then reconnect.",
            "403 Client Error": "Your GitGuardian API token is missing a required scope or access level for this data. Grant the required read scopes (and Manager access level for incidents), then reconnect.",
        }

    def get_schemas(
        self,
        config: GitguardianSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            has_incremental = bool(INCREMENTAL_FIELDS.get(endpoint))
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                supports_append=has_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=GITGUARDIAN_ENDPOINTS[endpoint].should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def _check_base_url(self, config: GitguardianSourceConfig, team_id: int) -> tuple[str, str | None]:
        """Resolve and safety-check the base URL. Returns (base_url, error)."""
        base_url = resolve_base_url(config.base_url)
        url_error = validate_base_url(base_url)
        if url_error:
            return base_url, url_error
        host = urlsplit(base_url).hostname or ""
        host_ok, host_error = _is_host_safe(host, team_id)
        if not host_ok:
            return base_url, host_error or "GitGuardian host is not allowed"
        return base_url, None

    def validate_credentials(
        self, config: GitguardianSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        base_url, error = self._check_base_url(config, team_id)
        if error:
            return False, error
        if schema_name is not None and schema_name in GITGUARDIAN_ENDPOINTS:
            # Per-schema check: confirm the token's scopes actually cover this endpoint.
            reason = check_endpoint_access(config.api_key, base_url, schema_name)
            if reason:
                return False, reason
            return True, None
        # Source-create check: one cheap scope-free probe confirming the token is genuine. Missing
        # scopes surface per table via get_endpoint_permissions instead of blocking the source.
        return validate_gitguardian_credentials(config.api_key, base_url)

    def get_endpoint_permissions(
        self, config: GitguardianSourceConfig, team_id: int, endpoints: list[str]
    ) -> dict[str, str | None]:
        base_url, error = self._check_base_url(config, team_id)
        if error:
            return dict.fromkeys(endpoints, error)
        return {
            endpoint: check_endpoint_access(config.api_key, base_url, endpoint)
            if endpoint in GITGUARDIAN_ENDPOINTS
            else None
            for endpoint in endpoints
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GitGuardianResumeConfig]:
        return ResumableSourceManager[GitGuardianResumeConfig](inputs, GitGuardianResumeConfig)

    def source_for_pipeline(
        self,
        config: GitguardianSourceConfig,
        resumable_source_manager: ResumableSourceManager[GitGuardianResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        base_url, error = self._check_base_url(config, inputs.team_id)
        if error:
            raise ValueError(error)

        return gitguardian_source(
            api_key=config.api_key,
            base_url=base_url,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
