from typing import cast

from sources.looker._config import LookerSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class LookerSource(SimpleSource[LookerSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LOOKER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.LOOKER,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Looker",
            iconPath="/static/services/looker.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
