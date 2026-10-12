from typing import cast

from sources.pubnub._config import PubnubSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class PubnubSource(SimpleSource[PubnubSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PUBNUB

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PUBNUB,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="PubNub",
            iconPath="/static/services/pubnub.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
