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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import NewsApiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.news_api.news_api import (
    NewsApiResumeConfig,
    news_api_source,
    validate_credentials as validate_news_api_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.news_api.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    NEWS_API_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class NewsApiSource(ResumableSource[NewsApiSourceConfig, NewsApiResumeConfig]):
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://newsapi.org/docs"

    # get_schemas iterates a static endpoint catalog with no I/O, so the table list is safe to
    # render in public docs without credentials.
    lists_tables_without_credentials = True

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NEWSAPI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.NEWS_API,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="NewsAPI",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["newsapi", "news api"],
            caption="""Enter your NewsAPI key to pull live and historical news articles into the PostHog Data warehouse.

Create a free API key at [newsapi.org](https://newsapi.org/register). The search query drives the `everything` and `top_headlines` tables; the `sources` table lists available publishers.

Note: NewsAPI's free Developer plan is limited to articles from the last month and is for development/testing only — a paid plan is required for production use and older articles.""",
            iconPath="/static/services/news_api.png",
            docsUrl="https://posthog.com/docs/cdp/sources/news-api",
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
                        name="query",
                        label="Search query",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="e.g. bitcoin OR ethereum",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="language",
                        label="Language (optional, 2-letter code)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="e.g. en",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.news_api.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked NewsAPI key returns 401. Retrying can never satisfy a credential
            # problem, so stop the sync. Match the stable status text, not the per-request path/query.
            "401 Client Error": "Your NewsAPI key is invalid or has been revoked. Create a new key at newsapi.org and reconnect.",
            "426 Client Error": "This request requires a paid NewsAPI plan (e.g. articles older than one month, or beyond the free-tier result limit). Upgrade your plan at newsapi.org and reconnect.",
        }

    def get_schemas(
        self,
        config: NewsApiSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if endpoint == "everything":
                return "Full article search. Incremental sync windows on publishedAt; NewsAPI caps reachable results per window at 100"
            if endpoint == "top_headlines":
                return "Curated breaking-news headlines. Full refresh only (no date filter)"
            if endpoint == "sources":
                return "The publisher catalog behind top-headlines. Full refresh only"
            return None

        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = NEWS_API_ENDPOINTS[endpoint]
            has_incremental = endpoint_config.supports_incremental and bool(INCREMENTAL_FIELDS.get(endpoint))
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                supports_append=has_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                description=_description(endpoint),
                detected_primary_keys=endpoint_config.primary_keys,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: NewsApiSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_news_api_credentials(config.api_key):
            return True, None

        return False, "Invalid NewsAPI key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[NewsApiResumeConfig]:
        return ResumableSourceManager[NewsApiResumeConfig](inputs, NewsApiResumeConfig)

    def source_for_pipeline(
        self,
        config: NewsApiSourceConfig,
        resumable_source_manager: ResumableSourceManager[NewsApiResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return news_api_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            query=config.query,
            language=config.language or None,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
