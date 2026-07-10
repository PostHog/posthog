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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GiphySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.giphy.giphy import (
    GiphyResumeConfig,
    giphy_source,
    validate_credentials as validate_giphy_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.giphy.settings import ENDPOINTS, GIPHY_ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GiphySource(ResumableSource[GiphySourceConfig, GiphyResumeConfig]):
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://developers.giphy.com/docs/api/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GIPHY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GIPHY,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Giphy",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your GIPHY API key to pull trending content, search results, and the category taxonomy into the PostHog Data warehouse.

Create an API key in the [GIPHY Developer Dashboard](https://developers.giphy.com/dashboard/). All GIPHY content is full-refresh only — the API has no incremental sync filter.

The search tables (`gifs_search`, `stickers_search`) only appear once you set a search query below.""",
            iconPath="/static/services/giphy.png",
            docsUrl="https://developers.giphy.com/docs/api",
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
                        name="search_query",
                        label="Search query",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="e.g. cats",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.giphy.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # A bad/banned key surfaces as a requests HTTPError when `_fetch_page` calls
            # `raise_for_status()`. Retrying can never satisfy a credential problem. The
            # per-request query/offset varies, but the status text and base host are stable.
            "401 Client Error: Unauthorized for url: https://api.giphy.com": "Your GIPHY API key is invalid or has been revoked. Create a new key in the GIPHY Developer Dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.giphy.com": "Your GIPHY API key has been banned or lacks access. Check the key in the GIPHY Developer Dashboard, then reconnect.",
            # A search table syncing without a query (e.g. the query was cleared after setup) raises a
            # ValueError before any HTTP call. Retrying can't fix missing config, so fail fast.
            "requires a search query": "The search tables (gifs_search, stickers_search) need a search query. Set one on the source and reconnect.",
        }

    def get_schemas(
        self,
        config: GiphySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        has_query = bool((config.search_query or "").strip())

        schemas = []
        for endpoint in ENDPOINTS:
            endpoint_config = GIPHY_ENDPOINTS[endpoint]
            # Search tables can't be populated without a query, so hide them until one is set.
            if endpoint_config.requires_query and not has_query:
                continue
            schemas.append(
                SourceSchema(
                    name=endpoint,
                    supports_incremental=False,
                    supports_append=False,
                    incremental_fields=[],
                    should_sync_default=endpoint_config.should_sync_default,
                    description="Full refresh only — GIPHY exposes no incremental sync filter",
                )
            )

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: GiphySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_giphy_credentials(config.api_key):
            return True, None

        return False, "Invalid GIPHY API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GiphyResumeConfig]:
        return ResumableSourceManager[GiphyResumeConfig](inputs, GiphyResumeConfig)

    def source_for_pipeline(
        self,
        config: GiphySourceConfig,
        resumable_source_manager: ResumableSourceManager[GiphyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return giphy_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            search_query=config.search_query,
        )
