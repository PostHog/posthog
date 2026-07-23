from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awscostandusagereport import (
    AwsCostAndUsageReportSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AwsCostAndUsageReportSource(SimpleSource[AwsCostAndUsageReportSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSCOSTANDUSAGEREPORT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AWS_COST_AND_USAGE_REPORT,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Amazon Web Services (AWS Cost and Usage Report)",
            iconPath="/static/services/aws_cost_and_usage_report.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
