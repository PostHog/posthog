from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cdcopendata import (
    CdcOpenDataSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CdcOpenDataSource(SimpleSource[CdcOpenDataSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CDCOPENDATA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CDC_OPEN_DATA,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="CDC Open Data (data.cdc.gov)",
            iconPath="/static/services/cdc_open_data.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
