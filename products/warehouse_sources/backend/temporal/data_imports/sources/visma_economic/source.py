from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.vismaeconomic import (
    VismaEconomicSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class VismaEconomicSource(SimpleSource[VismaEconomicSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.VISMAECONOMIC

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.VISMAECONOMIC,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Visma Economic",
            iconPath="/static/services/visma_economic.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
