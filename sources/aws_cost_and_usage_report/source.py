from typing import cast

from sources.aws_cost_and_usage_report._config import AwsCostAndUsageReportSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AwsCostAndUsageReportSource(SimpleSource[AwsCostAndUsageReportSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSCOSTANDUSAGEREPORT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AWSCOSTANDUSAGEREPORT,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Amazon Web Services (AWS Cost and Usage Report)",
            iconPath="/static/services/aws_cost_and_usage_report.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
