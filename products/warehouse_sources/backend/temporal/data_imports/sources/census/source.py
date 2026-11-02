import datetime
from typing import Optional, cast

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.census.census import (
    UNSERVED_TABLE_ERROR,
    CensusResumeConfig,
    census_source,
    get_endpoint_permissions as get_census_endpoint_permissions,
    validate_credentials as validate_census_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.census.settings import (
    CENSUS_API_V1,
    CENSUS_API_V2,
    get_census_endpoints,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    FieldType,
    ResumableSource,
    VersionDeprecation,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.census import CensusSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CensusSource(ResumableSource[CensusSourceConfig, CensusResumeConfig]):
    codebase_detection = detect(pypi=("airflow-provider-census",))

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://fivetran.com/docs/activations/rest-api"
    supported_versions = (CENSUS_API_V1, CENSUS_API_V2)
    default_version = CENSUS_API_V2
    deprecated_versions = (VersionDeprecation(version=CENSUS_API_V1, sunset_at=datetime.date(2027, 1, 15)),)

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CENSUS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Census rejected the API token. Generate a new token in Census and reconnect. New connections need an Activations personal access token from your Fivetran user settings.",
            "403 Client Error": "Your Census API token does not have access to this resource. Check the token's permissions in Census and reconnect.",
            UNSERVED_TABLE_ERROR: "This table is not available on the Census API version this source uses. Deselect the table, or remove its API version override.",
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
        endpoints = get_census_endpoints(self.resolve_api_version(api_version))
        return build_endpoint_schemas(
            endpoints, {name: config.incremental_fields for name, config in endpoints.items()}, names
        )

    def validate_credentials(
        self,
        config: CensusSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_census_credentials(
            config.api_key, config.region, self.resolve_api_version(api_version), schema_name=schema_name
        )

    def get_endpoint_permissions(
        self,
        config: CensusSourceConfig,
        team_id: int,
        endpoints: list[str],
        api_version: str | None = None,
    ) -> dict[str, str | None]:
        return get_census_endpoint_permissions(
            config.api_key, config.region, endpoints, self.resolve_api_version(api_version)
        )

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
            api_version=self.resolve_api_version(inputs.api_version),
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CENSUS,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Census (Fivetran)",
            caption="""Enter a Census API access token to sync your syncs, sync runs, sources, destinations, and datasets.

Use an Activations personal access token. Create one in Fivetran under your Activations **User settings → Personal access tokens**. Activations tokens are separate from Fivetran API keys and Fivetran personal access tokens.
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
            releaseStatus=ReleaseStatus.BETA,
        )
