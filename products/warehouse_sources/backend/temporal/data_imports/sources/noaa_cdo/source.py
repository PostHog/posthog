from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.noaacdo import (
    NoaaCdoSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.noaa_cdo.noaa_cdo import (
    NoaaCdoResumeConfig,
    noaa_cdo_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.noaa_cdo.settings import (
    API_DOCS_URL,
    AUTH_ERROR,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    REQUEST_ERROR,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class NoaaCdoSource(ResumableSource[NoaaCdoSourceConfig, NoaaCdoResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = API_DOCS_URL

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NOAACDO

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            AUTH_ERROR: AUTH_ERROR,
            "401 Client Error": AUTH_ERROR,
            "403 Client Error": AUTH_ERROR,
            REQUEST_ERROR: REQUEST_ERROR,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.noaa_cdo.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: NoaaCdoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only={"data"})

    def validate_credentials(
        self,
        config: NoaaCdoSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, team_id, self.resolve_api_version(api_version))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[NoaaCdoResumeConfig]:
        return ResumableSourceManager(inputs, NoaaCdoResumeConfig)

    def source_for_pipeline(
        self,
        config: NoaaCdoSourceConfig,
        resumable_source_manager: ResumableSourceManager[NoaaCdoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return noaa_cdo_source(
            config=config,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            manager=resumable_source_manager,
            api_version=self.resolve_api_version(inputs.api_version),
            should_use_incremental_field=inputs.should_use_incremental_field,
            last_value=inputs.db_incremental_field_last_value,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.NOAACDO,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="NOAA Climate Data Online (NCEI)",
            iconPath="/static/services/noaa_cdo.png",
            caption=(
                "Request a free API token from [NOAA](https://www.ncei.noaa.gov/cdo-web/token). "
                "Select one dataset and one station for observations. Reference tables can cover the whole dataset. "
                "Observations use metric units. Incremental sync reads the previous seven days again. "
                "Use a full refresh to collect older corrections. "
                "NOAA limits each token to five requests per second and 10,000 requests per day."
            ),
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="dataset_id",
                        label="Dataset ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="GHCND",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="station_id",
                        label="Station ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="GHCND:USW00094728",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Start date",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="YYYY-MM-DD",
                        secret=False,
                    ),
                ],
            ),
        )
