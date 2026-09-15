from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.circleso import (
    CircleSoSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CircleSoSource(SimpleSource[CircleSoSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CIRCLESO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CIRCLESO,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Circle (circle.so)",
            iconPath="/static/services/circle_so.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
