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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gologin import (
    GoLoginSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gologin.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gologin.gologin import (
    GoLoginResumeConfig,
    gologin_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gologin.settings import (
    AUTH_ERROR,
    ENDPOINTS,
    PERMISSION_ERROR,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GoLoginSource(ResumableSource[GoLoginSourceConfig, GoLoginResumeConfig]):
    lists_tables_without_credentials = True
    api_docs_url = "https://api.gologin.com/docs"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOLOGIN

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {"401 Client Error": AUTH_ERROR, "403 Client Error": PERMISSION_ERROR}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: GoLoginSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, {}, names)

    def validate_credentials(
        self,
        config: GoLoginSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GoLoginResumeConfig]:
        return ResumableSourceManager(inputs, GoLoginResumeConfig)

    def source_for_pipeline(
        self,
        config: GoLoginSourceConfig,
        resumable_source_manager: ResumableSourceManager[GoLoginResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return gologin_source(
            config.api_key, inputs.schema_name, inputs.team_id, inputs.job_id, resumable_source_manager
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GOLOGIN,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="GoLogin",
            iconPath="/static/services/gologin.png",
            caption="Find your GoLogin API key in Settings > API.",
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
