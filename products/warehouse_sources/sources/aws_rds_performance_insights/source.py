from typing import cast

from products.warehouse_sources.sources.aws_rds_performance_insights._config import (
    AwsRdsPerformanceInsightsSourceConfig,
)
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AwsRdsPerformanceInsightsSource(SimpleSource[AwsRdsPerformanceInsightsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSRDSPERFORMANCEINSIGHTS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AWSRDSPERFORMANCEINSIGHTS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Amazon Web Services (Amazon RDS Performance Insights)",
            iconPath="/static/services/aws_rds_performance_insights.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
