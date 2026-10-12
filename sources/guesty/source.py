from typing import cast

from sources.guesty._config import GuestySourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GuestySource(SimpleSource[GuestySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GUESTY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GUESTY,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Guesty",
            iconPath="/static/services/guesty.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
