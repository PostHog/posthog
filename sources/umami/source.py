from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

from sources.umami._config import UmamiSourceConfig


@SourceRegistry.register
class UmamiSource(SimpleSource[UmamiSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.UMAMI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.UMAMI,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Umami",
            iconPath="/static/services/umami.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
