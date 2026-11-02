from typing import cast

from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from products.warehouse_sources.sources.tana._config import TanaSourceConfig


@SourceRegistry.register
class TanaSource(SimpleSource[TanaSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TANA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TANA,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Tana",
            iconPath="/static/services/tana.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
