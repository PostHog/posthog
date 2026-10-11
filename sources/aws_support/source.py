from typing import cast

from sources.aws_support._config import AwsSupportSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AwsSupportSource(SimpleSource[AwsSupportSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSSUPPORT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AWSSUPPORT,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Amazon Web Services (AWS Support)",
            iconPath="/static/services/aws_support.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
