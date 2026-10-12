from typing import cast

from sources.aws_health._config import AwsHealthSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AwsHealthSource(SimpleSource[AwsHealthSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSHEALTH

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AWSHEALTH,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Amazon Web Services (AWS Health)",
            iconPath="/static/services/aws_health.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
