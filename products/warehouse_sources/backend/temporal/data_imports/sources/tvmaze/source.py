from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tvmaze import TVMazeSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.tvmaze.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tvmaze.tvmaze import (
    TVMazeResumeConfig,
    check_connection,
    tvmaze_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TVMazeSource(ResumableSource[TVMazeSourceConfig, TVMazeResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # TVmaze exposes no version token (no /vN/ path, header, or dated release), so the
    # framework's unversioned default applies.
    api_docs_url = "https://www.tvmaze.com/api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TVMAZE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # The public API needs no credentials; a 401/403 means TVmaze is refusing the
        # caller (e.g. an IP-level block), which a retry cannot fix.
        return {
            "401 Client Error": "TVmaze rejected the request. Try again later.",
            "403 Client Error": "TVmaze rejected the request. Try again later.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.tvmaze.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: TVMazeSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: TVMazeSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        # No credentials to validate — just confirm the public API is reachable.
        return check_connection()

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TVMazeResumeConfig]:
        return ResumableSourceManager[TVMazeResumeConfig](inputs, TVMazeResumeConfig)

    def source_for_pipeline(
        self,
        config: TVMazeSourceConfig,
        resumable_source_manager: ResumableSourceManager[TVMazeResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return tvmaze_source(
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TV_MAZE,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="TVmaze",
            caption="Import TV show and people data from the free public TVmaze API. No API key is required. TVmaze data is licensed CC BY-SA, which requires attribution and share-alike.",
            docsUrl="https://posthog.com/docs/cdp/sources/tvmaze",
            iconPath="/static/services/tvmaze.png",
            keywords=["tv", "television", "tv shows"],
            fields=cast(list[FieldType], []),
            releaseStatus=ReleaseStatus.ALPHA,
        )
