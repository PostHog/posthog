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
from products.warehouse_sources.backend.temporal.data_imports.sources.firecrawl.firecrawl import (
    FirecrawlResumeConfig,
    firecrawl_source,
    validate_credentials as validate_firecrawl_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.firecrawl.settings import (
    ENDPOINTS,
    FIRECRAWL_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FirecrawlSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

_ENDPOINT_DESCRIPTIONS: dict[str, str] = {
    "team_activity": "Job activity log. Firecrawl only retains the last 24 hours, so sync frequently to accumulate history - older activity cannot be backfilled.",
    "monitor_checks": "Change-detection runs, one row per check across every monitor. Off by default: it fans out one request per monitor.",
}


@SourceRegistry.register
class FirecrawlSource(ResumableSource[FirecrawlSourceConfig, FirecrawlResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog - safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FIRECRAWL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FIRECRAWL,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Firecrawl",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Firecrawl API key to pull your Firecrawl account activity and usage into the PostHog Data warehouse.

You can create an API key in your [Firecrawl dashboard](https://www.firecrawl.dev/app/api-keys). A single key grants access to all of the tables below.""",
            iconPath="/static/services/firecrawl.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/firecrawl",
            keywords=["scraping", "crawling", "web data", "firecrawl"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="fc-...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.firecrawl.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked key surfaces as an HTTPError from raise_for_status(). Retrying can
            # never satisfy a credential problem, so stop the sync. Match the stable status text plus
            # base host, not the per-request path.
            "401 Client Error: Unauthorized for url: https://api.firecrawl.dev": "Your Firecrawl API key is invalid or has been revoked. Create a new key in your Firecrawl dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.firecrawl.dev": "Your Firecrawl API key does not have access to this data. Check the key in your Firecrawl dashboard, then reconnect.",
        }

    def get_schemas(
        self,
        config: FirecrawlSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = FIRECRAWL_ENDPOINTS[endpoint]
            # Every endpoint is full-refresh: Firecrawl has no server-side timestamp filter to drive a
            # genuine incremental sync (see settings.py).
            return SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                should_sync_default=endpoint_config.should_sync_default,
                description=_ENDPOINT_DESCRIPTIONS.get(endpoint),
                detected_primary_keys=endpoint_config.primary_keys,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: FirecrawlSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # A Firecrawl key is all-or-nothing (no per-endpoint scopes), so the same token probe covers
        # both source-create (schema_name=None) and the per-schema check.
        if validate_firecrawl_credentials(config.api_key):
            return True, None
        return False, "Invalid Firecrawl API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[FirecrawlResumeConfig]:
        return ResumableSourceManager[FirecrawlResumeConfig](inputs, FirecrawlResumeConfig)

    def source_for_pipeline(
        self,
        config: FirecrawlSourceConfig,
        resumable_source_manager: ResumableSourceManager[FirecrawlResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return firecrawl_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
