from typing import cast

from sources.navan._config import NavanSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class NavanSource(SimpleSource[NavanSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NAVAN

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.NAVAN,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Navan",
            iconPath="/static/services/navan.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
