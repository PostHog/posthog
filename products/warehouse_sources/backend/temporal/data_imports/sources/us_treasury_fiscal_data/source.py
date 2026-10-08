from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import ResumableSource
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ustreasuryfiscaldata import (
    UsTreasuryFiscalDataSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.us_treasury_fiscal_data.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.us_treasury_fiscal_data.settings import (
    ACCESS_ERROR,
    API_DOCS_URL,
    BASE_URL,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.us_treasury_fiscal_data.us_treasury_fiscal_data import (
    FiscalDataResumeConfig,
    fiscal_data_source,
    validate_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class UsTreasuryFiscalDataSource(ResumableSource[UsTreasuryFiscalDataSourceConfig, FiscalDataResumeConfig]):
    lists_tables_without_credentials = True
    api_docs_url = API_DOCS_URL

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.USTREASURYFISCALDATA

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            f"401 Client Error: Unauthorized for url: {BASE_URL}": ACCESS_ERROR,
            f"403 Client Error: Forbidden for url: {BASE_URL}": ACCESS_ERROR,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: UsTreasuryFiscalDataSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=ENDPOINTS)

    def validate_credentials(
        self,
        config: UsTreasuryFiscalDataSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[FiscalDataResumeConfig]:
        return ResumableSourceManager(inputs, FiscalDataResumeConfig)

    def source_for_pipeline(
        self,
        config: UsTreasuryFiscalDataSourceConfig,
        resumable_source_manager: ResumableSourceManager[FiscalDataResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return fiscal_data_source(inputs, resumable_source_manager)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.USTREASURYFISCALDATA,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="US Treasury Fiscal Data",
            caption="Import public US Treasury data. No API key or account is required.",
            iconPath="/static/services/us_treasury_fiscal_data.png",
            fields=[],
            releaseStatus=ReleaseStatus.ALPHA,
        )
