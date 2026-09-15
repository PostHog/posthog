from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sapfieldglass import (
    SAPFieldglassSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SAPFieldglassSource(SimpleSource[SAPFieldglassSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SAPFIELDGLASS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SAPFIELDGLASS,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="SAP Fieldglass",
            iconPath="/static/services/sap_fieldglass.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
