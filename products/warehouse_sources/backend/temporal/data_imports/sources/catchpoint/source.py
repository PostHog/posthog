from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.catchpoint.catchpoint import (
    CatchpointResumeConfig,
    catchpoint_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.catchpoint.settings import (
    AUTH_ERROR,
    ENDPOINTS,
    INCOMPLETE_ERROR,
    PERMISSION_ERROR,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.catchpoint import (
    CatchpointSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CatchpointSource(ResumableSource[CatchpointSourceConfig, CatchpointResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = ("v3",)
    default_version = "v3"
    api_docs_url = "https://io.catchpoint.com/api/swagger/index.html"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CATCHPOINT

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": AUTH_ERROR,
            "403 Client Error": PERMISSION_ERROR,
            INCOMPLETE_ERROR: INCOMPLETE_ERROR,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.catchpoint.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: CatchpointSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, {}, names)

    def validate_credentials(
        self,
        config: CatchpointSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config.api_key, self.resolve_api_version(api_version), team_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CatchpointResumeConfig]:
        return ResumableSourceManager(inputs, CatchpointResumeConfig)

    def source_for_pipeline(
        self,
        config: CatchpointSourceConfig,
        resumable_source_manager: ResumableSourceManager[CatchpointResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return catchpoint_source(
            api_key=config.api_key,
            api_version=self.resolve_api_version(inputs.api_version),
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CATCHPOINT,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Catchpoint Systems",
            caption="Create an API key in Catchpoint under Settings > Integrations > REST API > Add Consumer.",
            iconPath="/static/services/catchpoint.png",
            releaseStatus=ReleaseStatus.ALPHA,
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
                    )
                ],
            ),
        )
