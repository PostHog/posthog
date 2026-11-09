from typing import cast

from products.warehouse_sources.sources.mews._config import MewsSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class MewsSource(SimpleSource[MewsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MEWS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MEWS,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Mews",
            iconPath="/static/services/mews.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
