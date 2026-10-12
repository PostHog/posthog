from typing import cast

from sources.aws_connect._config import AwsConnectSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


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
