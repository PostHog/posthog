from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.sinch._config import SinchSourceConfig


@SourceRegistry.register
class SinchSource(SimpleSource[SinchSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SINCH

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SINCH,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Sinch",
            iconPath="/static/services/sinch.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
