from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

from sources.holded._config import HoldedSourceConfig


@SourceRegistry.register
class HoldedSource(SimpleSource[HoldedSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HOLDED

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.HOLDED,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Holded (Visma)",
            iconPath="/static/services/holded.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
