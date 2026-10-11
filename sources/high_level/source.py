from typing import cast

from sources.high_level._config import HighLevelSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class HighLevelSource(SimpleSource[HighLevelSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HIGHLEVEL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.HIGHLEVEL,
            category=DataWarehouseSourceCategory.CRM,
            label="High Level",
            iconPath="/static/services/high_level.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
