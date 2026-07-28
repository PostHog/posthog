from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awssavingsplans import (
    AwsSavingsPlansSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AwsSavingsPlansSource(SimpleSource[AwsSavingsPlansSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSSAVINGSPLANS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AWS_SAVINGS_PLANS,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Amazon Web Services (AWS Savings Plans / Cost Explorer)",
            iconPath="/static/services/aws_savings_plans.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
