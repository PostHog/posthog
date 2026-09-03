from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.framer.framer import (
    framer_source,
    validate_credentials as validate_framer_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.framer.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.framer import FramerSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FramerSource(SimpleSource[FramerSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # Framer has no REST API; the official surface is the `framer-api` SDK's WebSocket
    # protocol, and the pinned version is the SDK release whose message contract we speak
    # (sent as the `sdkVersion` connection parameter).
    supported_versions = ("0.1.29",)
    default_version = "0.1.29"
    api_docs_url = "https://www.framer.com/developers/server-api-introduction"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FRAMER

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "Framer API error UNAUTHORIZED": "Framer rejected the API key for this project. Generate a new API key in the project's Site Settings → General and reconnect.",
            "Framer API error INVALID_REQUEST": "The Framer project URL or ID is invalid. Update the source with your project URL (https://framer.com/projects/...) or project ID.",
            "Invalid Framer project URL or ID": "The Framer project URL or ID is invalid. Update the source with your project URL (https://framer.com/projects/...) or project ID.",
            # Framer's headless loader raises this when a code component the project uses
            # references a module the headless runtime can't resolve — a defect in the
            # project's own code components, not a transient server condition, so it fails
            # identically on every retry until the project is fixed.
            "ensureComponentsInLoader": "A code component in this Framer project references a module Framer's API can't load. Check the project's code components for missing or broken dependencies, then resync.",
        }

    def get_retryable_errors(self) -> set[str]:
        # Transient channel conditions the next Temporal attempt recovers from: a busy
        # headless pool, a concurrent-session collision, a dropped connection, or an
        # egress-proxy hiccup.
        return {
            "Framer API error POOL_EXHAUSTED",
            "Framer API error TOKEN_SESSION_LIMIT",
            "Framer API error TIMEOUT",
            "Framer API error CONNECTION_CLOSED",
            "Framer API error PROXY",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.framer.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: FramerSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: FramerSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_framer_credentials(config.project_url, config.api_key, self.resolve_api_version(api_version))

    def source_for_pipeline(self, config: FramerSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return framer_source(
            project=config.project_url,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            protocol_version=self.resolve_api_version(inputs.api_version),
            logger=inputs.logger,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FRAMER,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Framer",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Sync your Framer site's pages, CMS collections and items, locales, redirects, and deployments into the PostHog Data warehouse.

Create an API key in your Framer project under **Site Settings → General**, then paste your project URL (https://framer.com/projects/...) and the API key. API keys are project-specific, so add one source per project.""",
            iconPath="/static/services/framer.png",
            docsUrl="https://posthog.com/docs/cdp/sources/framer",
            keywords=["cms", "website", "landing pages", "site builder"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="project_url",
                        label="Project URL or ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://framer.com/projects/...",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
