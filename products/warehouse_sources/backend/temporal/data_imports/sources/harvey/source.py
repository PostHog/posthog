from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import HarveySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.harvey.harvey import (
    HarveyResumeConfig,
    check_endpoint_access,
    harvey_source,
    validate_credentials as validate_harvey_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.harvey.settings import (
    ENDPOINTS,
    HARVEY_ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HarveySource(ResumableSource[HarveySourceConfig, HarveyResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HARVEY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.HARVEY,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Harvey",
            caption="""Enter your Harvey API token to pull audit logs, usage and query history, client matters, and Vault project metadata into the PostHog Data warehouse.

Create an API token in Harvey workspace settings under **API Tokens** (if you don't see that section, ask your Harvey Customer Success Manager to enable API access).

Each token carries a per-endpoint permissions list — grant access for the endpoints you want to sync: audit logs, history exports, client matters, and Vault.
""",
            iconPath="/static/services/harvey.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/harvey",
            keywords=["legal", "ai", "audit logs", "usage"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US (api.harvey.ai)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (eu.api.harvey.ai)", value="eu"),
                            SourceFieldSelectConfigOption(label="AU (au.api.harvey.ai)", value="au"),
                        ],
                    ),
                ],
            ),
            unreleasedSource=True,
            releaseStatus=ReleaseStatus.ALPHA,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.harvey.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # requests raises "401 Client Error: Unauthorized for url: <regional host>/..." -
        # match the stable status text so all three regional hosts are covered.
        return {
            "401 Client Error: Unauthorized for url": "Your Harvey API token is invalid or has been revoked. Create a new token in Harvey workspace settings (Settings → API Tokens), then reconnect.",
            "403 Client Error: Forbidden for url": "Your Harvey API token does not have permission for this endpoint. Enable it in the token's permissions list in Harvey workspace settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: HarveySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Audit logs are immutable, so append-only is the only incremental mode we offer.
        append_only_endpoints = {"audit_logs"}

        def _description(endpoint: str) -> str | None:
            if endpoint in ("usage_history", "query_history"):
                return "Only syncs the last year on initial sync (Harvey API limit)"
            if endpoint in ("client_matters", "vault_projects"):
                return "Full refresh only"
            return None

        def _build_schema(endpoint: str) -> SourceSchema:
            has_incremental = bool(INCREMENTAL_FIELDS.get(endpoint))
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental and endpoint not in append_only_endpoints,
                supports_append=has_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=HARVEY_ENDPOINTS[endpoint].should_sync_default,
                description=_description(endpoint),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: HarveySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if not validate_harvey_credentials(config.api_key, config.region):
            return False, "Invalid Harvey API token"

        # Harvey tokens have per-endpoint permissions; when asked about a specific schema,
        # confirm the token can actually reach that endpoint.
        if schema_name is not None and schema_name in HARVEY_ENDPOINTS:
            reason = check_endpoint_access(config.api_key, config.region, schema_name)
            if reason is not None:
                return False, reason

        return True, None

    def get_endpoint_permissions(
        self, config: HarveySourceConfig, team_id: int, endpoints: list[str]
    ) -> dict[str, str | None]:
        return {
            endpoint: check_endpoint_access(config.api_key, config.region, endpoint)
            if endpoint in HARVEY_ENDPOINTS
            else None
            for endpoint in endpoints
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[HarveyResumeConfig]:
        return ResumableSourceManager[HarveyResumeConfig](inputs, HarveyResumeConfig)

    def source_for_pipeline(
        self,
        config: HarveySourceConfig,
        resumable_source_manager: ResumableSourceManager[HarveyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return harvey_source(
            api_key=config.api_key,
            region=config.region,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
