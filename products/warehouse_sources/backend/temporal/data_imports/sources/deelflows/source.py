from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.deelflows import (
    DeelFlowsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DeelFlowsSource(SimpleSource[DeelFlowsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DEELFLOWS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.DEELFLOWS,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="DeelFlows",
            iconPath="/static/services/deelflows.png",
            keywords=["whatsapp", "cart recovery", "marketing automation"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
