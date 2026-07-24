from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ustreasuryfiscaldata import (
    UsTreasuryFiscalDataSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class UsTreasuryFiscalDataSource(SimpleSource[UsTreasuryFiscalDataSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.USTREASURYFISCALDATA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.US_TREASURY_FISCAL_DATA,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="US Treasury Fiscal Data",
            iconPath="/static/services/us_treasury_fiscal_data.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
