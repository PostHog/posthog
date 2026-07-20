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
from products.warehouse_sources.backend.temporal.data_imports.sources.dataforseo.dataforseo import (
    DEFAULT_LANGUAGE_NAME,
    DEFAULT_LOCATION_NAME,
    DataForSEOResumeConfig,
    dataforseo_source,
    validate_credentials as validate_dataforseo_credentials,
    validate_targets,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dataforseo.settings import DATAFORSEO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DataForSEOSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DataForSEOSource(ResumableSource[DataForSEOSourceConfig, DataForSEOResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DATAFORSEO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DATA_FOR_SEO,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="DataForSEO",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["seo", "serp", "keyword research", "backlinks", "rank tracking"],
            caption="""Enter your DataForSEO API credentials and the domains you want to track to pull SEO metrics like Google rankings, keywords, competitors, and backlinks into the PostHog Data warehouse.

Find your API login and password on the [DataForSEO API access page](https://app.dataforseo.com/api-access).

Note: DataForSEO bills per API request, so every sync consumes account credits. The backlinks summary table also requires an active Backlinks API subscription.""",
            iconPath="/static/services/dataforseo.png",
            docsUrl="https://posthog.com/docs/cdp/sources/dataforseo",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_login",
                        label="API login",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="you@example.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_password",
                        label="API password",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="targets",
                        label="Target domains (comma-separated)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="example.com, posthog.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="location_name",
                        label="Location",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder=DEFAULT_LOCATION_NAME,
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="language_name",
                        label="Language",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder=DEFAULT_LANGUAGE_NAME,
                        secret=False,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        invalid_credentials_message = (
            "Your DataForSEO API credentials are invalid. Find your API login and password at "
            "https://app.dataforseo.com/api-access, then reconnect."
        )
        insufficient_funds_message = (
            "Your DataForSEO account has insufficient funds for this sync. Top up your balance at "
            "https://app.dataforseo.com, then resync."
        )
        return {
            # Match on the stable host, not the per-request path.
            "401 Client Error: Unauthorized for url: https://api.dataforseo.com": invalid_credentials_message,
            "402 Client Error: Payment Required for url: https://api.dataforseo.com": insufficient_funds_message,
            "DataForSEO API error [40100]": invalid_credentials_message,
            "DataForSEO API error [40200]": insufficient_funds_message,
            "DataForSEO API error [40210]": insufficient_funds_message,
            "DataForSEO API error [40201]": "Your DataForSEO account is blocked. Contact DataForSEO support to restore access, then resync.",
            "DataForSEO API error [40203]": "Your DataForSEO daily spending limit was exceeded. Raise the limit in your DataForSEO account settings or wait for it to reset, then resync.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.dataforseo.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: DataForSEOSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # No DataForSEO live endpoint exposes a server-side updated-since filter, so every table
        # is full refresh only.
        schemas = [
            SourceSchema(
                name=endpoint.name,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                detected_primary_keys=endpoint.primary_keys,
                should_sync_default=endpoint.should_sync_default,
                description=endpoint.description,
            )
            for endpoint in DATAFORSEO_ENDPOINTS.values()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: DataForSEOSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        _, targets_error = validate_targets(config.targets)
        if targets_error:
            return False, targets_error

        if validate_dataforseo_credentials(config.api_login, config.api_password):
            return True, None

        return False, "Invalid DataForSEO API credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DataForSEOResumeConfig]:
        return ResumableSourceManager[DataForSEOResumeConfig](inputs, DataForSEOResumeConfig)

    def source_for_pipeline(
        self,
        config: DataForSEOSourceConfig,
        resumable_source_manager: ResumableSourceManager[DataForSEOResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        # Re-validate here so a previously-saved oversized target list can't trigger a runaway sync.
        targets, targets_error = validate_targets(config.targets)
        if targets_error:
            raise ValueError(f"DataForSEO source misconfigured: {targets_error}")

        return dataforseo_source(
            api_login=config.api_login,
            api_password=config.api_password,
            targets=targets,
            location_name=(config.location_name or "").strip() or DEFAULT_LOCATION_NAME,
            language_name=(config.language_name or "").strip() or DEFAULT_LANGUAGE_NAME,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
