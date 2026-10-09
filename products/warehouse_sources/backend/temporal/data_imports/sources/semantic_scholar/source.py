from typing import cast

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.semanticscholar import (
    SemanticScholarSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.semantic_scholar.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.semantic_scholar.semantic_scholar import (
    SemanticScholarResumeConfig,
    semantic_scholar_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.semantic_scholar.settings import (
    API_DOCS_URL,
    AUTH_ERROR,
    ENDPOINTS,
    LIMIT_ERROR,
    QUERY_ERROR,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SemanticScholarSource(ResumableSource[SemanticScholarSourceConfig, SemanticScholarResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = API_DOCS_URL

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SEMANTICSCHOLAR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SEMANTICSCHOLAR,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Semantic Scholar (Allen Institute for AI)",
            iconPath="/static/services/semantic_scholar.png",
            releaseStatus=ReleaseStatus.ALPHA,
            caption=(
                "Request an API key from the [Semantic Scholar API page]"
                "(https://www.semanticscholar.org/product/api#api-key-form). "
                "Enter a specific query to select papers. Citations and references make additional requests for each matching paper. "
                "Each sync refreshes all results. Links without a related paper ID are excluded."
            ),
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        secret=True,
                        placeholder="",
                    ),
                    SourceFieldInputConfig(
                        name="query",
                        label="Paper search query",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        secret=False,
                        placeholder='"graph neural networks"',
                    ),
                ],
            ),
        )

    def get_schemas(
        self,
        config: SemanticScholarSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Publication dates cannot identify metadata updates or papers added after their publication date.
        return [
            SourceSchema(
                name=name, supports_incremental=False, supports_append=False, should_sync_default=name == "papers"
            )
            for name in ENDPOINTS
            if names is None or name in names
        ]

    def validate_credentials(
        self,
        config: SemanticScholarSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, self.resolve_api_version(api_version))

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": AUTH_ERROR,
            "403 Client Error": AUTH_ERROR,
            "400 Client Error": QUERY_ERROR,
            "Invalid API Key": AUTH_ERROR,
            LIMIT_ERROR: LIMIT_ERROR,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SemanticScholarResumeConfig]:
        return ResumableSourceManager(inputs, SemanticScholarResumeConfig)

    def source_for_pipeline(
        self,
        config: SemanticScholarSourceConfig,
        resumable_source_manager: ResumableSourceManager[SemanticScholarResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return semantic_scholar_source(
            config, inputs, resumable_source_manager, self.resolve_api_version(inputs.api_version)
        )
