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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import NewsDataSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.newsdata.newsdata import (
    NewsDataResumeConfig,
    newsdata_source,
    validate_credentials as validate_newsdata_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.newsdata.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    NEWSDATA_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class NewsDataSource(ResumableSource[NewsDataSourceConfig, NewsDataResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NEWSDATA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.NEWS_DATA,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="NewsData.io",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your NewsData.io API key to pull news articles into the PostHog Data warehouse.

You can find your API key on your [NewsData.io dashboard](https://newsdata.io/dashboard).

Page size and daily request credits are determined by your NewsData.io plan.""",
            iconPath="/static/services/newsdata.png",
            docsUrl="https://posthog.com/docs/cdp/sources/newsdata",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="pub_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.newsdata.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked key surfaces as HTTP 401 when `_fetch_page` calls
            # `raise_for_status()`. Retrying can't fix a credential problem, so stop the sync.
            "401 Client Error: Unauthorized for url: https://newsdata.io": "Your NewsData.io API key is invalid or has been revoked. Find your key on the NewsData.io dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://newsdata.io": "Your NewsData.io plan does not allow access to this data. Check your plan on the NewsData.io dashboard, then reconnect.",
        }

    def get_schemas(
        self,
        config: NewsDataSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = NEWSDATA_ENDPOINTS[endpoint]
            # Only date-filter endpoints (archive, crypto) have a genuine server-side timestamp filter.
            has_incremental = endpoint_config.supports_date_filter and bool(INCREMENTAL_FIELDS.get(endpoint))
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
        self, config: NewsDataSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_newsdata_credentials(config.api_key):
            return True, None

        return False, "Invalid NewsData.io API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[NewsDataResumeConfig]:
        return ResumableSourceManager[NewsDataResumeConfig](inputs, NewsDataResumeConfig)

    def source_for_pipeline(
        self,
        config: NewsDataSourceConfig,
        resumable_source_manager: ResumableSourceManager[NewsDataResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return newsdata_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
