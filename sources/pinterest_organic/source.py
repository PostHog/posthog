from typing import cast

from sources.pinterest_organic._config import PinterestOrganicSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class PinterestOrganicSource(SimpleSource[PinterestOrganicSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PINTERESTORGANIC

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PINTERESTORGANIC,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Pinterest (Pinterest API v5, organic content)",
            iconPath="/static/services/pinterest_organic.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
