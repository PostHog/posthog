from typing import cast

from sources.sailthru._config import SailthruSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class SailthruSource(SimpleSource[SailthruSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SAILTHRU

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SAILTHRU,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Sailthru",
            iconPath="/static/services/sailthru.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
