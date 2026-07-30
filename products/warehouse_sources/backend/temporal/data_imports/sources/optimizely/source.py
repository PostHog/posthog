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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import OptimizelySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.optimizely.optimizely import (
    optimizely_source,
    validate_credentials as validate_optimizely_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.optimizely.settings import ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OptimizelySource(SimpleSource[OptimizelySourceConfig]):
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://library.optimizely.com/docs/api/app/v2/index.html"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OPTIMIZELY

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.optimizely.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.optimizely.com": "Optimizely authentication failed. Please check your personal access token.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.OPTIMIZELY,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Optimizely",
            caption="""Enter your Optimizely personal access token to pull your experimentation data into the PostHog Data warehouse.

An admin can generate a personal access token in Optimizely under Account Settings > API Access. Tokens are non-expiring. Project-scoped data (experiments, audiences, events, pages, campaigns) is synced across all projects the token can access.""",
            iconPath="/static/services/optimizely.com.png",
            docsUrl="https://posthog.com/docs/cdp/sources/optimizely",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="Personal access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_schemas(
        self,
        config: OptimizelySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # No v2 list endpoint has an updated-since filter; the entities are
        # low-volume experiment config, so full refresh is the honest mode.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: OptimizelySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_optimizely_credentials(config.api_token):
            return True, None

        return False, "Invalid Optimizely personal access token"

    def source_for_pipeline(self, config: OptimizelySourceConfig, inputs: SourceInputs) -> SourceResponse:
        return optimizely_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
        )
