from typing import cast

from sources.fauna._config import FaunaSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class FaunaSource(SimpleSource[FaunaSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FAUNA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.FAUNA,
            category=DataWarehouseSourceCategory.DATABASES,
            label="Fauna",
            iconPath="/static/services/fauna.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
