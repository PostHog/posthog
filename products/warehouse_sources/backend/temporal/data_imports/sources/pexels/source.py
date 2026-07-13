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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PexelsSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pexels.pexels import (
    PexelsResumeConfig,
    pexels_source,
    validate_credentials as validate_pexels_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pexels.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PEXELS_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PexelsSource(ResumableSource[PexelsSourceConfig, PexelsResumeConfig]):
    # `get_schemas` iterates a static endpoint catalog with no I/O, so the table list is safe to
    # publish to public docs without credentials.
    lists_tables_without_credentials = True

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PEXELS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PEXELS,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Pexels",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Pexels API key to pull Pexels stock photo and video catalog data into the PostHog Data warehouse.

Generate an API key from your [Pexels API dashboard](https://www.pexels.com/api/).

Attribution to Pexels and to the photographer/videographer is required when you use Pexels content — see the [Pexels API guidelines](https://www.pexels.com/api/documentation/#guidelines).""",
            iconPath="/static/services/pexels.png",
            docsUrl="https://posthog.com/docs/cdp/sources/pexels",
            unreleasedSource=True,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Your Pexels API key",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="search_query",
                        label="Search query",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="e.g. nature",
                        secret=False,
                        caption="Optional. When set, the **search_photos** and **search_videos** tables become available and sync content matching this query.",
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.pexels.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked Pexels API key surfaces as a requests HTTPError when `_fetch_page`
            # calls `raise_for_status()`. Retrying can never satisfy a credential problem, so stop the
            # sync. Match the stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.pexels.com": "Your Pexels API key is invalid or has been revoked. Generate a new key from your Pexels API dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.pexels.com": "Your Pexels API key is not permitted to access this data. Check your Pexels account, then reconnect.",
        }

    def get_schemas(
        self,
        config: PexelsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        has_search_query = bool((config.search_query or "").strip())

        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = PEXELS_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                # Pexels has no server-side incremental filter, so every table is full refresh only.
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                description=endpoint_config.description,
            )

        # Search tables require a query; only offer them when one is configured.
        schemas = [
            _build_schema(endpoint)
            for endpoint in ENDPOINTS
            if has_search_query or not PEXELS_ENDPOINTS[endpoint].requires_query
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: PexelsSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_pexels_credentials(config.api_key):
            return True, None

        return False, "Invalid Pexels API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PexelsResumeConfig]:
        return ResumableSourceManager[PexelsResumeConfig](inputs, PexelsResumeConfig)

    def source_for_pipeline(
        self,
        config: PexelsSourceConfig,
        resumable_source_manager: ResumableSourceManager[PexelsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return pexels_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            search_query=config.search_query,
        )
