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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.getdx import GetdxSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.getdx.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.getdx.getdx import (
    API_ERROR,
    AUTH_ERROR,
    PERMISSION_ERROR,
    GetdxResumeConfig,
    getdx_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.getdx.settings import ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GetdxSource(ResumableSource[GetdxSourceConfig, GetdxResumeConfig]):
    lists_tables_without_credentials = True
    api_docs_url = "https://docs.getdx.com/webapi/overview/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GETDX

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GETDX,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="DX (getdx.com)",
            iconPath="/static/services/getdx.png",
            caption="Create a token in DX under Admin > Organization tokens. "
            "Enable snapshots:read and users:read for their tables. "
            "Scorecards need scorecards:read and DX Fabric.",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Organization token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        placeholder="",
                        required=True,
                        secret=True,
                    )
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            AUTH_ERROR: AUTH_ERROR,
            PERMISSION_ERROR: PERMISSION_ERROR,
            API_ERROR: API_ERROR,
            "401 Client Error": AUTH_ERROR,
            "403 Client Error": PERMISSION_ERROR,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: GetdxSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return [
            SourceSchema(name=name, supports_incremental=False, supports_append=False)
            for name in ENDPOINTS
            if names is None or name in names
        ]

    def validate_credentials(
        self,
        config: GetdxSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config.api_key, team_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GetdxResumeConfig]:
        return ResumableSourceManager(inputs, GetdxResumeConfig)

    def source_for_pipeline(
        self,
        config: GetdxSourceConfig,
        resumable_source_manager: ResumableSourceManager[GetdxResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return getdx_source(config, inputs, resumable_source_manager)
