from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ukcompanieshouse import (
    UkCompaniesHouseSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class UkCompaniesHouseSource(SimpleSource[UkCompaniesHouseSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.UKCOMPANIESHOUSE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.UK_COMPANIES_HOUSE,
            category=DataWarehouseSourceCategory.CRM,
            label="Companies House (UK government)",
            iconPath="/static/services/uk_companies_house.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
