from typing import cast

from sources.ringcentral._config import RingCentralSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class RingCentralSource(SimpleSource[RingCentralSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RINGCENTRAL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.RINGCENTRAL,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="RingCentral",
            iconPath="/static/services/ringcentral.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
