from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.amazonkinesis import (
    AmazonKinesisSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


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
