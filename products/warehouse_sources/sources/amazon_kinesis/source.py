from typing import cast

from products.warehouse_sources.sources.amazon_kinesis._config import AmazonKinesisSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AmazonKinesisSource(SimpleSource[AmazonKinesisSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AMAZONKINESIS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AMAZONKINESIS,
            category=DataWarehouseSourceCategory.DATABASES,
            label="Amazon Kinesis",
            iconPath="/static/services/aws-kinesis.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
