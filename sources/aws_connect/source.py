from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

from sources.aws_connect._config import AwsConnectSourceConfig


@SourceRegistry.register
class AwsConnectSource(SimpleSource[AwsConnectSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSCONNECT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AWSCONNECT,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Amazon Web Services (Amazon Connect)",
            iconPath="/static/services/aws_connect.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
