from typing import cast

from sources.aws_athena._config import AwsAthenaSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AwsAthenaSource(SimpleSource[AwsAthenaSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSATHENA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AWSATHENA,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Amazon Web Services (Amazon Athena)",
            iconPath="/static/services/aws_athena.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
