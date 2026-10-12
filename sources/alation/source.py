from typing import cast

from sources.alation._config import AlationSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AlationSource(SimpleSource[AlationSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ALATION

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ALATION,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Alation",
            iconPath="/static/services/alation.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
