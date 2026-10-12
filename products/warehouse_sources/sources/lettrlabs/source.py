from typing import cast

from products.warehouse_sources.sources.lettrlabs._config import LettrLabsSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class LettrLabsSource(SimpleSource[LettrLabsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LETTRLABS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.LETTRLABS,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="LettrLabs",
            iconPath="/static/services/lettrlabs.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
