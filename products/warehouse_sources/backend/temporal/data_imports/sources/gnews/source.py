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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GNewsSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gnews.gnews import (
    GNewsResumeConfig,
    gnews_source,
    validate_credentials as validate_gnews_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gnews.settings import (
    ENDPOINTS,
    GNEWS_ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

# GNews's fixed set of top-headline categories (https://gnews.io/docs/v4#top-headlines-endpoint).
_CATEGORIES = [
    "general",
    "world",
    "nation",
    "business",
    "technology",
    "entertainment",
    "sports",
    "science",
    "health",
]


@SourceRegistry.register
class GNewsSource(ResumableSource[GNewsSourceConfig, GNewsResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GNEWS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.G_NEWS,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="GNews",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your GNews API key to pull worldwide news articles into the PostHog Data warehouse.

You can find your API key in your [GNews dashboard](https://gnews.io/dashboard).

The **Search query** drives the `articles` table (keyword search), and the **Category** drives the `top_headlines` table. GNews caps every query at 1000 articles, and free plans return fewer results per request with truncated content.""",
            iconPath="/static/services/gnews.png",
            docsUrl="https://posthog.com/docs/cdp/sources/gnews",
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
                        placeholder="posthog OR analytics",
                        secret=False,
                    ),
                    SourceFieldSelectConfig(
                        name="category",
                        label="Category",
                        required=True,
                        defaultValue="general",
                        options=[
                            SourceFieldSelectConfigOption(label=category.capitalize(), value=category)
                            for category in _CATEGORIES
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="language",
                        label="Language (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="en",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="country",
                        label="Country (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="us",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.gnews.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or missing key surfaces as an HTTPError when `_fetch_page` calls
            # `raise_for_status()`. Retrying can't fix a credential problem, so stop the sync.
            "401 Client Error: Unauthorized for url: https://gnews.io": "Your GNews API key is invalid. Create a new key in your GNews dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://gnews.io": "Your GNews plan does not permit this request, or its daily request quota is exhausted. Upgrade your plan or reconnect once the quota resets.",
        }

    def get_schemas(
        self,
        config: GNewsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if endpoint == "articles":
                return "Keyword search results for the configured query. Append-only by publish time."
            return "Breaking news for the configured category. Append-only by publish time."

        def _build_schema(endpoint: str) -> SourceSchema:
            return SourceSchema(
                name=endpoint,
                # GNews exposes a genuine server-side `from` filter on publishedAt, so both tables
                # support incremental. There is no updated-record cursor, so they're append-only.
                supports_incremental=True,
                supports_append=True,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=GNEWS_ENDPOINTS[endpoint].should_sync_default,
                description=_description(endpoint),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: GNewsSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_gnews_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GNewsResumeConfig]:
        return ResumableSourceManager[GNewsResumeConfig](inputs, GNewsResumeConfig)

    def source_for_pipeline(
        self,
        config: GNewsSourceConfig,
        resumable_source_manager: ResumableSourceManager[GNewsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return gnews_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            query=config.query,
            category=config.category,
            language=config.language,
            country=config.country,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
