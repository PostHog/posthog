from typing import cast

from sources.amazon_cloudwatch._config import AmazonCloudWatchSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AmazonCloudWatchSource(SimpleSource[AmazonCloudWatchSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AMAZONCLOUDWATCH

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AMAZONCLOUDWATCH,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Amazon CloudWatch",
            iconPath="/static/services/amazon_cloudwatch.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
