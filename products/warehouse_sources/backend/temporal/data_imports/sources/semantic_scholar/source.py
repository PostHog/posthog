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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.errors import auth_non_retryable_errors
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.semanticscholar import (
    SemanticScholarSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.semantic_scholar.semantic_scholar import (
    SemanticScholarResumeConfig,
    semantic_scholar_source,
    validate_author_search,
    validate_paper_search,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.semantic_scholar.settings import (
    AUTHORS_ENDPOINT,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SEMANTIC_SCHOLAR_BASE_URL,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SemanticScholarSource(ResumableSource[SemanticScholarSourceConfig, SemanticScholarResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog, safe for public docs
    # The Academic Graph API has no path segment, header, or param version - "1.0" in its docs
    # is a documentation label, not something a caller selects.
    api_docs_url = "https://api.semanticscholar.org/api-docs/graph"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SEMANTICSCHOLAR

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            **auth_non_retryable_errors(host=SEMANTIC_SCHOLAR_BASE_URL, service="Semantic Scholar"),
            f"400 Client Error: Bad Request for url: {SEMANTIC_SCHOLAR_BASE_URL}/paper/search/bulk": (
                "Semantic Scholar rejected the search query. It may match too many papers (queries are "
                "capped at 10 million results) or use invalid syntax. Narrow the query and try again."
            ),
            f"400 Client Error: Bad Request for url: {SEMANTIC_SCHOLAR_BASE_URL}/author/search": (
                "Semantic Scholar rejected the author search query. Check the query and try again."
            ),
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.semantic_scholar.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: SemanticScholarSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: SemanticScholarSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if schema_name == AUTHORS_ENDPOINT:
            if not (config.author_query and config.author_query.strip()):
                return False, "Enter an author search query to sync the Authors table."
            return validate_author_search(config.api_key, config.author_query)

        return validate_paper_search(config.api_key, config.query)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SemanticScholarResumeConfig]:
        return ResumableSourceManager[SemanticScholarResumeConfig](inputs, SemanticScholarResumeConfig)

    def source_for_pipeline(
        self,
        config: SemanticScholarSourceConfig,
        resumable_source_manager: ResumableSourceManager[SemanticScholarResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return semantic_scholar_source(
            api_key=config.api_key,
            query=config.query,
            author_query=config.author_query,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SEMANTIC_SCHOLAR,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Semantic Scholar",
            caption="""Semantic Scholar is a free academic search engine covering more than 200 million papers.

Enter a search query to sync matching papers into the Data warehouse. Add an author search query too if you also want an Authors table.

Requests work without an API key, but share Semantic Scholar's public rate limit and may be throttled. Request a free key at [semanticscholar.org/product/api](https://www.semanticscholar.org/product/api#api-key-form) for a higher limit; approval can take a few days.""",
            iconPath="/static/services/semantic_scholar.png",
            docsUrl="https://posthog.com/docs/cdp/sources/semantic-scholar",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["research", "citations", "papers", "academic"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="query",
                        label="Search query",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="large language models",
                        secret=False,
                        caption="Papers matching this query sync into the Papers table. Use + for AND, "
                        "| for OR, - to exclude a term, and quotes for an exact phrase.",
                    ),
                    SourceFieldInputConfig(
                        name="author_query",
                        label="Author search query (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="Jane Smith",
                        secret=False,
                        caption="Authors matching this query sync into the Authors table. Leave blank to "
                        "skip the Authors table.",
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key (optional)",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
