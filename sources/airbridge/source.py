from typing import cast

from sources.airbridge._config import AirbridgeSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AirbridgeSource(SimpleSource[AirbridgeSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AIRBRIDGE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AIRBRIDGE,
            category=DataWarehouseSourceCategory.ADVERTISING,
            keywords=["mobile attribution", "mmp"],
            label="Airbridge",
            iconPath="/static/services/airbridge.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
