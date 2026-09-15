from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.nationbuilder import (
    NationBuilderSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class NationBuilderSource(SimpleSource[NationBuilderSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NATIONBUILDER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.NATIONBUILDER,
            category=DataWarehouseSourceCategory.CRM,
            label="NationBuilder",
            iconPath="/static/services/nationbuilder.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
