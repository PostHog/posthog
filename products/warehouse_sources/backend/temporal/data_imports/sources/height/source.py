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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import HeightSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.height.height import (
    height_source,
    validate_credentials as _height_validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.height.settings import ENDPOINTS, HEIGHT_ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HeightSource(SimpleSource[HeightSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HEIGHT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.HEIGHT,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Height",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Height API key to pull your project management data into the PostHog Data warehouse.

You can create an API key on the **Settings → API** page in [Height](https://height.app/). The key grants read access to your workspace's users, lists, and field templates.
""",
            iconPath="/static/services/height.png",
            docsUrl="https://posthog.com/docs/cdp/sources/height",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="secret_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.height.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.height.app": "Your Height API key is invalid or has been revoked. Generate a new key on the Settings → API page, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.height.app": "Your Height API key does not have access to this data. Check the key's permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: HeightSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — Height's list endpoints expose no server-side
        # timestamp filter without search params, so there is no incremental cursor to advance.
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
        self, config: HeightSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The API key is workspace-wide, so a single probe validates access to every schema.
        return _height_validate_credentials(config.api_key)

    def source_for_pipeline(self, config: HeightSourceConfig, inputs: SourceInputs) -> SourceResponse:
        if inputs.schema_name not in HEIGHT_ENDPOINTS:
            raise ValueError(f"Unknown Height schema '{inputs.schema_name}'")

        return height_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
        )
