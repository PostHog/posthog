from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

from sources.dragonboat._config import DragonboatSourceConfig


@SourceRegistry.register
class DragonboatSource(SimpleSource[DragonboatSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DRAGONBOAT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.DRAGONBOAT,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            iconPath="/static/services/dragonboat.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
