from typing import cast

from sources.getstream._config import GetStreamSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GetStreamSource(SimpleSource[GetStreamSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GETSTREAM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GETSTREAM,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Stream",
            iconPath="/static/services/getstream.png",
            keywords=["getstream", "chat", "activity feeds"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
