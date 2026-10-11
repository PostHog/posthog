from typing import cast

from sources.aws_trusted_advisor._config import AwsTrustedAdvisorSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AwsTrustedAdvisorSource(SimpleSource[AwsTrustedAdvisorSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSTRUSTEDADVISOR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AWSTRUSTEDADVISOR,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Amazon Web Services (AWS Trusted Advisor)",
            iconPath="/static/services/aws_trusted_advisor.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
