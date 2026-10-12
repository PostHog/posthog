from typing import cast

from sources.amazon_sns._config import AmazonSNSSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AmazonSNSSource(SimpleSource[AmazonSNSSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AMAZONSNS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AMAZONSNS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Amazon SNS",
            iconPath="/static/services/amazon_sns.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
