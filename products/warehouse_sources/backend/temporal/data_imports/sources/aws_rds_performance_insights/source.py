from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsrdsperformanceinsights import (
    AwsRdsPerformanceInsightsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AwsRdsPerformanceInsightsSource(SimpleSource[AwsRdsPerformanceInsightsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSRDSPERFORMANCEINSIGHTS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AWS_RDS_PERFORMANCE_INSIGHTS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Amazon Web Services (Amazon RDS Performance Insights)",
            iconPath="/static/services/aws_rds_performance_insights.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
