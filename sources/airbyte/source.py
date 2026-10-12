from typing import cast

from sources.airbyte._config import AirbyteSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AirbyteSource(SimpleSource[AirbyteSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AIRBYTE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AIRBYTE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Airbyte",
            iconPath="/static/services/airbyte.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
