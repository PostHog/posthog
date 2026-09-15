from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kameleoon import (
    KameleoonSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class KameleoonSource(SimpleSource[KameleoonSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KAMELEOON

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.KAMELEOON,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Kameleoon",
            iconPath="/static/services/kameleoon.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
