from typing import cast

from products.warehouse_sources.sources.aws_s3_tables._config import AwsS3TablesSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AwsS3TablesSource(SimpleSource[AwsS3TablesSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSS3TABLES

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AWSS3TABLES,
            category=DataWarehouseSourceCategory.DATABASES,
            label="Amazon S3 Tables",
            iconPath="/static/services/aws-s3.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
