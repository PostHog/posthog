from typing import cast

from sources.basecamp._config import BasecampSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class BasecampSource(SimpleSource[BasecampSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BASECAMP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.BASECAMP,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Basecamp",
            iconPath="/static/services/basecamp.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
