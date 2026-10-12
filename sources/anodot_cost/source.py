from typing import cast

from sources.anodot_cost._config import AnodotCostSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AnodotCostSource(SimpleSource[AnodotCostSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ANODOTCOST

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ANODOTCOST,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Anodot Cost (Umbrella Cost)",
            iconPath="/static/services/anodot_cost.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
