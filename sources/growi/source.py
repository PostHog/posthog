from typing import cast

from sources.growi._config import GrowiSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GrowiSource(SimpleSource[GrowiSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GROWI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GROWI,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Growi",
            iconPath="/static/services/growi.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
