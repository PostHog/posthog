from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.applovin.applovin import (
    AUTH_ERROR_PREFIX,
    BAD_REQUEST_ERROR_PREFIX,
    AppLovinResumeConfig,
    applovin_source,
    validate_credentials as validate_applovin_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.applovin.settings import (
    APPLOVIN_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.applovin import (
    AppLovinSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AppLovinSource(ResumableSource[AppLovinSourceConfig, AppLovinResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog, safe for public docs
    # The reporting endpoints under r.applovin.com carry no version token of any kind.
    api_docs_url = "https://support.applovin.com/en/max/reporting-apis/revenue-reporting-api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.APPLOVIN

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.applovin.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            AUTH_ERROR_PREFIX: "AppLovin rejected your Report Key. Generate a new one under your account menu > Keys in the AppLovin dashboard, then reconnect.",
            BAD_REQUEST_ERROR_PREFIX: "AppLovin rejected the report request. This usually means your account can't access the requested report.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.APP_LOVIN,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="AppLovin",
            caption="""Connect your AppLovin account to pull MAX mediation revenue, campaign spend, and cohort reporting into the PostHog Data warehouse.

Find your **Report Key** in the AppLovin dashboard: click your account in the top right, then **Keys**.

AppLovin only serves the last 45 days of report data, so anything older than that can't be backfilled.""",
            iconPath="/static/services/applovin.png",
            docsUrl="https://posthog.com/docs/cdp/sources/applovin",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["max", "appdiscovery", "axon", "mobile ads"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Report Key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_schemas(
        self,
        config: AppLovinSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Rows are aggregates that restate for a few days, so append would duplicate them.
        schemas = build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=ENDPOINTS)
        for schema in schemas:
            schema.detected_primary_keys = list(APPLOVIN_ENDPOINTS[schema.name].primary_keys)
        return schemas

    def validate_credentials(
        self,
        config: AppLovinSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_applovin_credentials(config.api_key):
            return True, None

        return False, "Invalid AppLovin Report Key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AppLovinResumeConfig]:
        return ResumableSourceManager[AppLovinResumeConfig](inputs, AppLovinResumeConfig)

    def source_for_pipeline(
        self,
        config: AppLovinSourceConfig,
        resumable_source_manager: ResumableSourceManager[AppLovinResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return applovin_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
