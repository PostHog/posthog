from typing import cast

from products.warehouse_sources.sources.miro._config import MiroSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class MiroSource(SimpleSource[MiroSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MIRO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MIRO,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Miro",
            iconPath="/static/services/miro.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
