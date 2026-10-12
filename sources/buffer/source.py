from typing import cast

from sources.buffer._config import BufferSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class BufferSource(SimpleSource[BufferSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BUFFER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.BUFFER,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Buffer",
            iconPath="/static/services/buffer.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
