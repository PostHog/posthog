from collections import defaultdict
from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.anthropic import (
    AnthropicResumeConfig,
    anthropic_source,
    check_analytics_access,
    check_rbac_group_access,
    check_rbac_role_access,
    validate_credentials as validate_anthropic_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.settings import (
    ANALYTICS_PATH_PREFIX,
    ANTHROPIC_ENDPOINTS,
    ENDPOINT_RETIRED_ERROR,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    RBAC_GROUPS_PATH,
    RBAC_ROLES_PATH,
    AccessFamily,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.anthropic import (
    AnthropicSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AnthropicSource(ResumableSource[AnthropicSourceConfig, AnthropicResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("2023-06-01",)
    default_version = "2023-06-01"
    api_docs_url = "https://platform.claude.com/docs/en/api/versioning"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ANTHROPIC

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ANTHROPIC,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Anthropic",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Anthropic Admin API key to pull your organization's Claude usage, cost, and admin data into the PostHog Data warehouse.

Create an Admin API key (prefixed `sk-ant-admin...`) in your [Anthropic Console](https://console.anthropic.com/settings/admin-keys). Only organization admins can create one, and the Admin API is not available for individual accounts.

Some tables need a Claude Enterprise key instead, created by your primary owner in [claude.ai organization settings](https://claude.ai/admin-settings/api-access). A key works with one API only, so pick the one that matches the tables you want.

The per-seat activity, cost and token usage tables, and the connector, plugin, skill and summary tables, come from the Claude Enterprise Analytics API. They need a Claude Enterprise key carrying the `read:analytics` scope.

The group, group membership and custom role tables come from the Claude Enterprise user management API. They need an Admin API key carrying the `read:rbac_groups` scope for the group tables, or `read:members` for the custom role tables.""",
            iconPath="/static/services/anthropic.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/anthropic",
            keywords=["llm", "claude", "ai usage", "cost"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Admin API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="sk-ant-admin...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.anthropic.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        rbac_group_denied = "This table comes from the Claude Enterprise user management API, which your key can't reach. Reconnect the source with an Admin API key created in claude.ai for all your linked organizations, carrying the read:rbac_groups scope, or turn this table's sync off."
        rbac_role_denied = "This table comes from the Claude Enterprise user management API, which your key can't reach. Reconnect the source with an Admin API key created in claude.ai carrying the read:members scope, or turn this table's sync off."
        return {
            # Matched before the generic 403 below, because the first matching pattern supplies the
            # message and a denial from this path is about a missing scope, not admin access.
            f"403 Client Error: Forbidden for url: https://api.anthropic.com{ANALYTICS_PATH_PREFIX}": "This table comes from the Claude Enterprise Analytics API, which your key can't reach. Reconnect the source with a Claude Enterprise key carrying the read:analytics scope, or turn this table's sync off.",
            # An organization that is not on Claude Enterprise does not serve these routes at all,
            # so a 404 here means the same thing as a 403 and must not retry either.
            f"403 Client Error: Forbidden for url: https://api.anthropic.com{RBAC_GROUPS_PATH}": rbac_group_denied,
            f"404 Client Error: Not Found for url: https://api.anthropic.com{RBAC_GROUPS_PATH}": rbac_group_denied,
            f"403 Client Error: Forbidden for url: https://api.anthropic.com{RBAC_ROLES_PATH}": rbac_role_denied,
            f"404 Client Error: Not Found for url: https://api.anthropic.com{RBAC_ROLES_PATH}": rbac_role_denied,
            "401 Client Error: Unauthorized for url: https://api.anthropic.com": "Your Anthropic Admin API key is invalid or has been revoked. Create a new Admin API key in the Anthropic Console, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.anthropic.com": "Your Anthropic API key does not have organization admin access. Use an Admin API key (prefixed sk-ant-admin) created by an organization admin, then reconnect.",
            ENDPOINT_RETIRED_ERROR: "Anthropic no longer offers this table, so it can't sync. PostHog has turned its sync off for you, and any rows already imported stay in your warehouse.",
        }

    def get_schemas(
        self,
        config: AnthropicSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = ANTHROPIC_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                supports_incremental=endpoint_config.supports_incremental,
                supports_append=endpoint_config.supports_append,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                default_incremental_lookback_seconds=endpoint_config.default_incremental_lookback_seconds,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def get_endpoint_permissions(
        self,
        config: AnthropicSourceConfig,
        team_id: int,
        endpoints: list[str],
        api_version: str | None = None,
    ) -> dict[str, str | None]:
        probes = {
            AccessFamily.ANALYTICS: check_analytics_access,
            AccessFamily.RBAC_GROUPS: check_rbac_group_access,
            AccessFamily.RBAC_ROLES: check_rbac_role_access,
        }
        permissions: dict[str, str | None] = dict.fromkeys(endpoints)
        by_family: dict[AccessFamily, list[str]] = defaultdict(list)
        for name in endpoints:
            endpoint_config = ANTHROPIC_ENDPOINTS.get(name)
            if endpoint_config is not None and endpoint_config.access_family is not None:
                by_family[endpoint_config.access_family].append(name)
        for family, names in by_family.items():
            # Every endpoint in a family needs the same access, so one probe answers for all of them.
            reason = probes[family](config.api_key)
            for name in names:
                permissions[name] = reason
        return permissions

    def validate_credentials(
        self,
        config: AnthropicSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_anthropic_credentials(config.api_key):
            return True, None

        return False, "Invalid Anthropic Admin API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AnthropicResumeConfig]:
        return ResumableSourceManager[AnthropicResumeConfig](inputs, AnthropicResumeConfig)

    def source_for_pipeline(
        self,
        config: AnthropicSourceConfig,
        resumable_source_manager: ResumableSourceManager[AnthropicResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return anthropic_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
