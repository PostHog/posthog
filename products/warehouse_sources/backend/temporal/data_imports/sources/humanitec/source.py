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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.humanitec import (
    HumanitecSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.humanitec.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.humanitec.humanitec import (
    HumanitecResumeConfig,
    humanitec_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.humanitec.settings import (
    API_DOCS_URL,
    AUTH_ERROR,
    ENDPOINTS,
    PERMISSION_ERROR,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HumanitecSource(ResumableSource[HumanitecSourceConfig, HumanitecResumeConfig]):
    lists_tables_without_credentials = True
    api_docs_url = API_DOCS_URL

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HUMANITEC

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {"401 Client Error": AUTH_ERROR, "403 Client Error": PERMISSION_ERROR}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: HumanitecSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, {}, names)

    def validate_credentials(
        self,
        config: HumanitecSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[HumanitecResumeConfig]:
        return ResumableSourceManager(inputs, HumanitecResumeConfig)

    def source_for_pipeline(
        self,
        config: HumanitecSourceConfig,
        resumable_source_manager: ResumableSourceManager[HumanitecResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return humanitec_source(config, inputs.schema_name, inputs.team_id, inputs.job_id, resumable_source_manager)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.HUMANITEC,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Humanitec",
            iconPath="/static/services/humanitec.png",
            releaseStatus=ReleaseStatus.ALPHA,
            caption=(
                "In Humanitec, open Service users. Select a user. Select Add new API token. "
                "Use a service user with read access to the applications and environments you want to sync. "
                "This source connects to the Platform Orchestrator API at api.humanitec.io."
            ),
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
                        name="organization_id",
                        label="Organization ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="example-org",
                        secret=False,
                    ),
                ],
            ),
        )
