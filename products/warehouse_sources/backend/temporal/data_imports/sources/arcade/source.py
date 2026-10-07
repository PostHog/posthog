from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.arcade import ArcadeSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ArcadeSource(SimpleSource[ArcadeSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ARCADE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ARCADE,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Arcade",
            keywords=["interactive demo", "product demo"],
            iconPath="/static/services/arcade.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
