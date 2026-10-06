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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.qonto import QontoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.qonto.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.qonto.qonto import (
    QontoResumeConfig,
    qonto_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.qonto.settings import (
    AUTH_ERROR,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PERMISSION_ERROR,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class QontoSource(ResumableSource[QontoSourceConfig, QontoResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://docs.qonto.com/get-started/general/versioning"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.QONTO

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {"401 Client Error": AUTH_ERROR, "403 Client Error": PERMISSION_ERROR}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: QontoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: QontoSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, self.resolve_api_version(api_version), schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[QontoResumeConfig]:
        return ResumableSourceManager(inputs, QontoResumeConfig)

    def source_for_pipeline(
        self,
        config: QontoSourceConfig,
        resumable_source_manager: ResumableSourceManager[QontoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return qonto_source(
            config=config,
            endpoint=inputs.schema_name,
            api_version=self.resolve_api_version(inputs.api_version),
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            manager=resumable_source_manager,
            incremental=inputs.should_use_incremental_field,
            last_value=inputs.db_incremental_field_last_value if inputs.should_use_incremental_field else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.QONTO,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Qonto",
            iconPath="/static/services/qonto.png",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="Find your organization login and secret key in Qonto under **Integrations and Partnerships > API key**.",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="login",
                        label="Organization login",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="example-company-1234",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="secret_key",
                        label="Secret key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
