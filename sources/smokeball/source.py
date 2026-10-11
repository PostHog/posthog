from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.smokeball._config import SmokeballSourceConfig


@SourceRegistry.register
class SmokeballSource(SimpleSource[SmokeballSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SMOKEBALL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SMOKEBALL,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Smokeball",
            iconPath="/static/services/smokeball.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
