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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sevenshifts import (
    SevenShiftsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sevenshifts.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sevenshifts.settings import (
    ACCESS_ERROR,
    AUTH_ERROR,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sevenshifts.sevenshifts import (
    SevenShiftsResumeConfig,
    sevenshifts_source,
    validate_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SevenShiftsSource(ResumableSource[SevenShiftsSourceConfig, SevenShiftsResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = ("2026-01-01",)
    default_version = "2026-01-01"
    api_docs_url = "https://developers.7shifts.com/reference/versioning"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SEVENSHIFTS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {"401 Client Error": AUTH_ERROR, "403 Client Error": ACCESS_ERROR}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: SevenShiftsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=ENDPOINTS)

    def validate_credentials(
        self,
        config: SevenShiftsSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, self.resolve_api_version(api_version))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SevenShiftsResumeConfig]:
        return ResumableSourceManager(inputs, SevenShiftsResumeConfig)

    def source_for_pipeline(
        self,
        config: SevenShiftsSourceConfig,
        resumable_source_manager: ResumableSourceManager[SevenShiftsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return sevenshifts_source(
            config=config,
            endpoint=inputs.schema_name,
            api_version=self.resolve_api_version(inputs.api_version),
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            last_value=inputs.db_incremental_field_last_value,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SEVENSHIFTS,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="7shifts",
            iconPath="/static/services/sevenshifts.png",
            caption="Create an access token in 7shifts under Settings > Developer Tools. Enter the matching company ID.",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="company_id",
                        label="Company ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="12345",
                        secret=False,
                    ),
                ],
            ),
        )
