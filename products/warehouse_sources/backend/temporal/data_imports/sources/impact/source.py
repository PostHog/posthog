from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.impact import ImpactSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.impact.impact import (
    ImpactResumeConfig,
    impact_source,
    validate_credentials as validate_impact_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.impact.settings import (
    DEFAULT_API_VERSION,
    ENDPOINTS,
    IMPACT_ENDPOINTS,
    INCREMENTAL_FIELDS,
    SUPPORTED_API_VERSIONS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ImpactSource(ResumableSource[ImpactSourceConfig, ImpactResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://integrations.impact.com/brand-api-reference/readme/introduction"

    supported_versions = SUPPORTED_API_VERSIONS
    default_version = DEFAULT_API_VERSION

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.IMPACT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.IMPACT,
            category=DataWarehouseSourceCategory.ADVERTISING,
            keywords=["impact.com", "impact radius"],
            label="impact.com",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your impact.com Account SID and Auth Token to pull your partnership data into the PostHog Data warehouse.

Find these in impact.com under **Settings > Technical > API**. Create a Read-Only access token, then copy its Account SID and Auth Token below.""",
            iconPath="/static/services/impact.png",
            docsUrl="https://posthog.com/docs/cdp/sources/impact",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="account_sid",
                        label="Account SID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="auth_token",
                        label="Auth token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.impact.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.impact.com": "Your Impact.com Account SID or Auth Token is invalid. Check your credentials, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.impact.com": "Your Impact.com token does not have access to this data. Check the token's permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: ImpactSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            has_incremental = bool(INCREMENTAL_FIELDS.get(endpoint))
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                supports_append=has_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=IMPACT_ENDPOINTS[endpoint].should_sync_default,
                description=IMPACT_ENDPOINTS[endpoint].description,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: ImpactSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_impact_credentials(config.account_sid, config.auth_token, self.resolve_api_version(api_version)):
            return True, None

        return False, "Invalid Impact.com Account SID or Auth Token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ImpactResumeConfig]:
        return ResumableSourceManager[ImpactResumeConfig](inputs, ImpactResumeConfig)

    def source_for_pipeline(
        self,
        config: ImpactSourceConfig,
        resumable_source_manager: ResumableSourceManager[ImpactResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return impact_source(
            account_sid=config.account_sid,
            auth_token=config.auth_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            api_version=self.resolve_api_version(inputs.api_version),
        )
