from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.amazoncloudwatch import (
    AmazonCloudWatchSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


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
