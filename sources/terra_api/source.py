from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.terra_api._config import TerraApiSourceConfig


@SourceRegistry.register
class TerraApiSource(SimpleSource[TerraApiSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TERRAAPI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TERRAAPI,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Terra API",
            iconPath="/static/services/terra_api.png",
            keywords=["wearables", "health", "fitness", "terra"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
