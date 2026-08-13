from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    FieldType,
    ResumableSource,
    VersionDeprecation,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.leadfeeder import (
    LeadfeederSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.leadfeeder import (
    LeadfeederResumeConfig,
    leadfeeder_source,
    validate_credentials as validate_leadfeeder_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.leadfeeder.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    LEADFEEDER_API_LEGACY,
    LEADFEEDER_DEFAULT_VERSION,
    LEADFEEDER_ENDPOINTS,
    LEADFEEDER_SUPPORTED_VERSIONS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LeadfeederSource(ResumableSource[LeadfeederSourceConfig, LeadfeederResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    api_docs_url = "https://docs.leadfeeder.com/api/"

    supported_versions = LEADFEEDER_SUPPORTED_VERSIONS
    default_version = LEADFEEDER_DEFAULT_VERSION
    # The vendor has deprecated the legacy Token API (maintenance-only, no new tokens issued) in favor
    # of the unified Dealfront API. No removal date is announced, so this is advisory (sunset_at=None):
    # existing legacy-pinned sources keep working and are not migrated automatically.
    deprecated_versions = (VersionDeprecation(version=LEADFEEDER_API_LEGACY, sunset_at=None),)

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
            keywords=["dealfront"],
            caption="""Enter your Dealfront (Leadfeeder) API key to pull your website visitor and lead data into the PostHog data warehouse. This syncs the **Accounts**, **Leads**, and **Visits** tables.

New connections use the unified Dealfront API. Create an API key in your Dealfront platform settings, under Personal, API keys.

The older Leadfeeder API (a token from your [Leadfeeder API settings](https://app.leadfeeder.com/settings/api)) is deprecated and no longer issues new tokens. Existing connections on it keep working.

Optionally set a **Start date** to bound the initial sync. Leave it blank to pull the last year of leads and visits.""",
            iconPath="/static/services/leadfeeder.png",
            docsUrl="https://posthog.com/docs/cdp/sources/leadfeeder",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API key",
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
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Discovery is version-independent: both generations expose the same accounts / leads / visits
        # tables with the same incremental fields, so the static catalog is identical whatever the pin.
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
        self,
        config: LeadfeederSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        # Pre-creation calls pass no pin and resolve to `default_version` (the unified API, what new
        # rows are stamped with); a legacy-pinned source revalidates against its own Token API.
        if validate_leadfeeder_credentials(config.api_token, self.resolve_api_version(api_version)):
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
            resumable_source_manager=resumable_source_manager,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            start_date_config=config.start_date or "",
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
            api_version=self.resolve_api_version(inputs.api_version),
        )
