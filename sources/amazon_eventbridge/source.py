from typing import cast

from sources.amazon_eventbridge._config import AmazonEventBridgeSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AmazonEventBridgeSource(SimpleSource[AmazonEventBridgeSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AMAZONEVENTBRIDGE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AMAZONEVENTBRIDGE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Amazon EventBridge",
            iconPath="/static/services/amazon_eventbridge.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
