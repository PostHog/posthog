from typing import cast

from sources.amazon_sqs._config import AmazonSQSSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AmazonSQSSource(SimpleSource[AmazonSQSSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AMAZONSQS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AMAZONSQS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Amazon SQS",
            iconPath="/static/services/amazon_sqs.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
