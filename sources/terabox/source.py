from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.terabox._config import TeraBoxSourceConfig


@SourceRegistry.register
class TeraBoxSource(SimpleSource[TeraBoxSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TERABOX

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TERABOX,
            category=DataWarehouseSourceCategory.FILE_STORAGE,
            label="TeraBox",
            iconPath="/static/services/terabox.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
