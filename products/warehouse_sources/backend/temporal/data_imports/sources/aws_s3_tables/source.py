from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awss3tables import (
    AwsS3TablesSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


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
