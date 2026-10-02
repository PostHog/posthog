import datetime as dt
from typing import Optional, cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.singular import (
    SingularSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.singular.settings import (
    DAILY_REPORT,
    DEFAULT_DIMENSIONS,
    DEFAULT_METRICS,
    DESCRIPTIONS,
    ENDPOINTS,
    HISTORY_DAYS,
    INCREMENTAL_FIELDS,
    LOOKUPS,
    REPORT_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.singular.singular import (
    ACCESS_ERROR,
    AUTH_ERROR,
    QUOTA_ERROR,
    REPORT_FAILED_ERROR,
    REQUEST_ERROR,
    RETRYABLE_ERROR,
    SingularReportQuery,
    SingularResumeConfig,
    parse_field_list,
    singular_source,
    validate_credentials as validate_singular_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

SOURCE_CAPTION = """Enter your Singular API key to sync campaign reports into the PostHog Data warehouse. You can find the key in Singular under **Developer Tools > API Keys**.

The `daily_report` table has one row per day for each combination of the dimensions you choose. Leave the dimensions and metrics empty to sync network campaign data: cost, impressions, clicks, and installs by app, source, OS, country, and campaign.

Every row counts toward your Singular daily row limit (3 million rows by default), so each dimension you add uses more of it."""


def report_query(config: SingularSourceConfig) -> SingularReportQuery:
    return SingularReportQuery(
        dimensions=parse_field_list(config.dimensions, DEFAULT_DIMENSIONS),
        metrics=parse_field_list(config.metrics, DEFAULT_METRICS),
        cohort_metrics=parse_field_list(config.cohort_metrics),
        cohort_periods=parse_field_list(config.cohort_periods),
    )


@SourceRegistry.register
class SingularSource(ResumableSource[SingularSourceConfig, SingularResumeConfig]):
    supported_versions = ("v2.0",)
    default_version = "v2.0"
    api_docs_url = "https://support.singular.net/hc/en-us/articles/360045245692-Reporting-API-Reference"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    history_lookback = dt.timedelta(days=HISTORY_DAYS)

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SINGULAR

    def resume_covers_run(
        self,
        *,
        incremental_or_append: bool,
        schema_name: str | None = None,
    ) -> bool:
        # A lookup table is one request, so a retry has nothing to continue from.
        return schema_name not in LOOKUPS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # The raised messages already name the fix and quote Singular's own error text.
        return {
            AUTH_ERROR: None,
            ACCESS_ERROR: None,
            REQUEST_ERROR: None,
            REPORT_FAILED_ERROR: None,
            QUOTA_ERROR: None,
        }

    def get_retryable_errors(self) -> set[str]:
        return {RETRYABLE_ERROR}

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SINGULAR,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Singular",
            caption=SOURCE_CAPTION,
            iconPath="/static/services/singular.png",
            docsUrl="https://posthog.com/docs/cdp/sources/singular",
            keywords=["mmp", "attribution", "marketing measurement"],
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="dimensions",
                        label="Dimensions",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder=",".join(DEFAULT_DIMENSIONS),
                        secret=False,
                        caption="Comma-separated dimension names from the Singular Reporting API. For a custom dimension, use its ID. If you change the dimensions later, run a full resync of the `daily_report` table.",
                    ),
                    SourceFieldInputConfig(
                        name="metrics",
                        label="Metrics",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder=",".join(DEFAULT_METRICS),
                        secret=False,
                        caption="Comma-separated metric names from the Singular Reporting API. For a conversion event, use its name from the `conversion_metrics` table, not its display name.",
                    ),
                    SourceFieldInputConfig(
                        name="cohort_metrics",
                        label="Cohort metrics",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="revenue",
                        secret=False,
                        caption="Comma-separated cohort metric names from the `cohort_metrics` table, such as `revenue`. Cohort metrics need at least one cohort period.",
                    ),
                    SourceFieldInputConfig(
                        name="cohort_periods",
                        label="Cohort periods",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="7d,30d",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.singular.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: SingularSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = build_endpoint_schemas(
            ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only={DAILY_REPORT}, descriptions=DESCRIPTIONS
        )
        for schema in schemas:
            if schema.supports_incremental:
                schema.default_incremental_lookback_seconds = REPORT_LOOKBACK_SECONDS
        return schemas

    def validate_credentials(
        self,
        config: SingularSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        query = report_query(config)
        if bool(query.cohort_metrics) != bool(query.cohort_periods):
            return False, "Cohort metrics and cohort periods go together. Fill in both fields or leave both empty."

        return validate_singular_credentials(config.api_key, self.resolve_api_version(api_version))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SingularResumeConfig]:
        return ResumableSourceManager[SingularResumeConfig](inputs, SingularResumeConfig)

    def source_for_pipeline(
        self,
        config: SingularSourceConfig,
        resumable_source_manager: ResumableSourceManager[SingularResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return singular_source(
            api_key=config.api_key,
            api_version=self.resolve_api_version(inputs.api_version),
            endpoint=inputs.schema_name,
            query=report_query(config),
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            history_start=inputs.history_start,
        )
