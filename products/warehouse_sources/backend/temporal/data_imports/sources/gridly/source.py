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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GridlySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gridly.gridly import (
    GridlyResumeConfig,
    gridly_source,
    validate_credentials as validate_gridly_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gridly.settings import ENDPOINTS, GRIDLY_ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GridlySource(ResumableSource[GridlySourceConfig, GridlyResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GRIDLY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GRIDLY,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Gridly",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Gridly API key and a View ID to pull that view's records into the PostHog Data warehouse.

Create an API key in your Gridly company settings under **Settings → API keys** (Owner or Admin access is required). Use a **Full Access** or **Read-only** key.

Find the **View ID** in Gridly by opening your grid, selecting a view, and opening the **API** panel — it looks like `v1v9jwwk1lwnkz`. For the default Master branch this is the same as the Grid ID.
""",
            iconPath="/static/services/gridly.png",
            docsUrl="https://posthog.com/docs/cdp/sources/gridly",
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
                        name="view_id",
                        label="View ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="v1v9jwwk1lwnkz",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.gridly.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or insufficiently-scoped API key surfaces as an HTTPError when a page fetch
            # calls `raise_for_status()`. Retrying can never satisfy a credential problem, so stop the
            # sync. Match the stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.gridly.com": "Your Gridly API key is invalid or has been revoked. Create a new API key in your Gridly company settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.gridly.com": "Your Gridly API key can't access this view. Grant the key access to the view (or use a Full Access key), then reconnect.",
        }

    def get_schemas(
        self,
        config: GridlySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Gridly exposes no server-side timestamp filter, so every table is full refresh only.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                detected_primary_keys=GRIDLY_ENDPOINTS[endpoint].primary_keys,
                should_sync_default=GRIDLY_ENDPOINTS[endpoint].should_sync_default,
                description=GRIDLY_ENDPOINTS[endpoint].description,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: GridlySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_gridly_credentials(config.api_key, config.view_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GridlyResumeConfig]:
        return ResumableSourceManager[GridlyResumeConfig](inputs, GridlyResumeConfig)

    def source_for_pipeline(
        self,
        config: GridlySourceConfig,
        resumable_source_manager: ResumableSourceManager[GridlyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return gridly_source(
            api_key=config.api_key,
            view_id=config.view_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
