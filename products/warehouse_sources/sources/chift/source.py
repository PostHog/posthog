from typing import cast

from products.warehouse_sources.sources.chift._config import ChiftSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class ChiftSource(SimpleSource[ChiftSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CHIFT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CHIFT,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Chift",
            iconPath="/static/services/chift.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
