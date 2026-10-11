from typing import cast

from sources.aws_cloudformation._config import AwsCloudformationSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AwsCloudformationSource(SimpleSource[AwsCloudformationSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSCLOUDFORMATION

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AWSCLOUDFORMATION,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Amazon Web Services (AWS CloudFormation)",
            iconPath="/static/services/aws_cloudformation.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
