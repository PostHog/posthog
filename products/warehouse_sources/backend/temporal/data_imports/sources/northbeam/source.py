from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.northbeam import (
    NorthbeamSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class NorthbeamSource(SimpleSource[NorthbeamSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NORTHBEAM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.NORTHBEAM,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Northbeam",
            iconPath="/static/services/northbeam.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
