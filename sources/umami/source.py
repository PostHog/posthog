from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.umami._config import UmamiSourceConfig


@SourceRegistry.register
class UmamiSource(SimpleSource[UmamiSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.UMAMI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.UMAMI,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Umami",
            iconPath="/static/services/umami.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
