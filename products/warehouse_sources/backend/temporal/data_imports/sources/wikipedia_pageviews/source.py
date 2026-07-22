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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.wikipediapageviews import (
    WikipediaPageviewsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.wikipedia_pageviews.settings import (
    ACCESS_OPTIONS,
    AGENT_OPTIONS,
    ARTICLE_PAGEVIEWS_ENDPOINT,
    DATA_START_DATE,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    MAX_ARTICLES,
    WIKIPEDIA_PAGEVIEWS_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.wikipedia_pageviews.wikipedia_pageviews import (
    NO_ARTICLES_ERROR,
    WikipediaPageviewsResumeConfig,
    _coerce_date,
    _parse_articles,
    validate_project,
    wikipedia_pageviews_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class WikipediaPageviewsSource(ResumableSource[WikipediaPageviewsSourceConfig, WikipediaPageviewsResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # `rest_v1` is the version segment of the Wikimedia REST API base path this source calls.
    supported_versions = ("rest_v1",)
    default_version = "rest_v1"
    api_docs_url = "https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WIKIPEDIAPAGEVIEWS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            NO_ARTICLES_ERROR: (
                "Add one or more article titles in the source settings to sync the article_pageviews table."
            ),
            "400 Client Error": (
                "The Wikimedia API rejected the request. Check the project domain, access method, "
                "and agent type settings."
            ),
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.wikipedia_pageviews.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: WikipediaPageviewsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            descriptions={name: endpoint.description for name, endpoint in WIKIPEDIA_PAGEVIEWS_ENDPOINTS.items()},
            # The per-article table needs article titles configured; don't default-enable a
            # table whose sync would immediately fail.
            should_sync_default={ARTICLE_PAGEVIEWS_ENDPOINT: bool(_parse_articles(config.article_names))},
        )

    def validate_credentials(
        self,
        config: WikipediaPageviewsSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if config.start_date and _coerce_date(config.start_date) is None:
            return False, "Start date must be in YYYY-MM-DD format."
        articles = _parse_articles(config.article_names)
        if schema_name == ARTICLE_PAGEVIEWS_ENDPOINT and not articles:
            return False, "Add one or more article titles in the source settings to sync this table."
        if len(articles) > MAX_ARTICLES:
            return False, f"Too many article titles. List at most {MAX_ARTICLES}."
        return validate_project(config.project, config.access, config.agent)

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[WikipediaPageviewsResumeConfig]:
        return ResumableSourceManager[WikipediaPageviewsResumeConfig](inputs, WikipediaPageviewsResumeConfig)

    def source_for_pipeline(
        self,
        config: WikipediaPageviewsSourceConfig,
        resumable_source_manager: ResumableSourceManager[WikipediaPageviewsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return wikipedia_pageviews_source(
            project=config.project,
            access=config.access,
            agent=config.agent,
            article_names=config.article_names,
            start_date=config.start_date,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.WIKIPEDIA_PAGEVIEWS,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Wikipedia Pageviews",
            keywords=["wikimedia", "wiki", "pageviews"],
            caption=(
                "Sync pageview statistics for any Wikimedia project (Wikipedia, Wiktionary, Commons, and more) "
                "from the public Wikimedia Analytics API. No credentials are required.\n\n"
                "Data is available from July 2015 onward and lands with a delay of about a day. "
                "To sync the `article_pageviews` table, list the article titles to track."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/wikipedia-pageviews",
            iconPath="/static/services/wikipedia_pageviews.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="project",
                        label="Project domain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="en.wikipedia.org",
                        secret=False,
                    ),
                    SourceFieldSelectConfig(
                        name="access",
                        label="Access method",
                        required=True,
                        defaultValue="all-access",
                        options=[
                            SourceFieldSelectConfigOption(label=label, value=value) for value, label in ACCESS_OPTIONS
                        ],
                    ),
                    SourceFieldSelectConfig(
                        name="agent",
                        label="Agent type",
                        required=True,
                        defaultValue="user",
                        options=[
                            SourceFieldSelectConfigOption(label=label, value=value) for value, label in AGENT_OPTIONS
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="article_names",
                        label="Article titles",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="Albert Einstein, Marie Curie",
                        secret=False,
                        caption="Comma-separated list of article titles for the article_pageviews table.",
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Start date",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder=DATA_START_DATE.isoformat(),
                        secret=False,
                        caption=f"Earliest day to sync (YYYY-MM-DD). Defaults to {DATA_START_DATE.isoformat()}, when Wikimedia pageview data begins.",
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
