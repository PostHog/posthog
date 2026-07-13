from typing import Optional, cast

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import LeadfeederSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.leadfeeder import (
    LeadfeederResumeConfig,
    leadfeeder_source,
    validate_credentials as validate_leadfeeder_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    LEADFEEDER_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LeadfeederSource(ResumableSource[LeadfeederSourceConfig, LeadfeederResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LEADFEEDER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LEADFEEDER,
            category=DataWarehouseSourceCategory.CRM,
            label="Leadfeeder",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            keywords=["dealfront"],
            caption="""Enter your Leadfeeder (Dealfront) API token to pull your website visitor and lead data into the PostHog Data warehouse.

Generate a token in your [Leadfeeder API settings](https://app.leadfeeder.com/settings/api). This uses the legacy Leadfeeder API (`Authorization: Token`), which syncs the **Accounts**, **Leads**, and **Visits** tables.

Optionally set a **Start date** to bound the initial sync — leave it blank to pull the last year of leads and visits.""",
            iconPath="/static/services/leadfeeder.png",
            docsUrl="https://posthog.com/docs/cdp/sources/leadfeeder",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Start date",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="2024-01-01",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # A missing/invalid Leadfeeder token surfaces as an HTTPError when `_fetch_page` calls
            # `raise_for_status()`. Retrying can never fix a credential problem. Match the stable
            # status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.leadfeeder.com": "Your Leadfeeder API token is invalid or has been revoked. Generate a new token in your Leadfeeder API settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.leadfeeder.com": "Your Leadfeeder API token is missing or does not have access to this data. Check the token in your Leadfeeder API settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: LeadfeederSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = LEADFEEDER_ENDPOINTS[endpoint]
            # Only endpoints with a server-side start_date/end_date filter are genuinely incremental.
            has_incremental = endpoint_config.supports_date_filter
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                supports_append=has_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: LeadfeederSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_leadfeeder_credentials(config.api_token):
            return True, None

        return (
            False,
            "Unable to verify your Leadfeeder API token. Check that the token is correct and that Leadfeeder is reachable.",
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[LeadfeederResumeConfig]:
        return ResumableSourceManager[LeadfeederResumeConfig](inputs, LeadfeederResumeConfig)

    def source_for_pipeline(
        self,
        config: LeadfeederSourceConfig,
        resumable_source_manager: ResumableSourceManager[LeadfeederResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return leadfeeder_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            start_date_config=config.start_date or "",
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
