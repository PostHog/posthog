from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.census.census import (
    CensusResumeConfig,
    census_source,
    validate_credentials as validate_census_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.census.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.census import CensusSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CensusSource(ResumableSource[CensusSourceConfig, CensusResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://fivetran.com/docs/activations/rest-api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CENSUS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Census rejected the API token. Generate a new workspace access token in Census (workspace settings → API Access) and reconnect.",
            "403 Client Error": "Your Census API token does not have access to this resource. Check the token's permissions in Census and reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.census.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: CensusSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Census has no server-side timestamp filter on any list endpoint (only page-based
        # pagination + creation-time ordering), so every table is full refresh only.
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: CensusSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_census_credentials(config.api_key, config.region, schema_name=schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CensusResumeConfig]:
        return ResumableSourceManager[CensusResumeConfig](inputs, CensusResumeConfig)

    def source_for_pipeline(
        self,
        config: CensusSourceConfig,
        resumable_source_manager: ResumableSourceManager[CensusResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return census_source(
            api_key=config.api_key,
            region=config.region,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CENSUS,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Census (Fivetran)",
            caption="""Enter a Census workspace API access token to sync your syncs, sync runs, sources, and destinations.

You can find or generate a workspace access token in Census under **Workspace settings → API Access**.
""",
            keywords=["reverse etl", "data activation", "fivetran"],
            docsUrl="https://posthog.com/docs/cdp/sources/census",
            iconPath="/static/services/census.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Workspace region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US (app.getcensus.com)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (app-eu.getcensus.com)", value="eu"),
                        ],
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
