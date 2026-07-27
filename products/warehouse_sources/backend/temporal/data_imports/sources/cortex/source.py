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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cortex.cortex import (
    cortex_source,
    validate_credentials as validate_cortex_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cortex.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cortex import CortexSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CortexSource(SimpleSource[CortexSourceConfig]):
    # `get_schemas` iterates a static endpoint catalog with no I/O, so the table list is safe to
    # render in public docs without credentials.
    lists_tables_without_credentials = True
    api_docs_url = "https://docs.cortex.io/api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CORTEX

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Cortex API key is invalid or has been revoked. Generate a new key in workspace Settings and reconnect.",
            "403 Client Error": "Your Cortex API key does not have the required read permissions. Check the key's permissions in workspace Settings and try again.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.cortex.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: CortexSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: CortexSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_cortex_credentials(config.api_key, schema_name=schema_name)

    def source_for_pipeline(self, config: CortexSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return cortex_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CORTEX,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Cortex",
            caption="""Enter your Cortex API key to sync your service catalog, scorecards, teams, and entity relationships into the PostHog Data warehouse.

Create an API key in your Cortex workspace under **Settings → API Keys**. The key needs read access to the catalog, scorecards, and teams you want to sync.""",
            docsUrl="https://posthog.com/docs/cdp/sources/cortex",
            iconPath="/static/services/cortex.png",
            keywords=["service catalog", "developer portal", "scorecards"],
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
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
