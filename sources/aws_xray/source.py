from typing import cast

from sources.aws_xray._config import AwsXraySourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AwsXraySource(SimpleSource[AwsXraySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSXRAY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AWSXRAY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Amazon Web Services (AWS X-Ray)",
            iconPath="/static/services/aws_xray.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
