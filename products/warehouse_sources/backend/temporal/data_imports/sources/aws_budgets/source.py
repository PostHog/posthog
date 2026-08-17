from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsbudgets import (
    AwsBudgetsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AwsBudgetsSource(SimpleSource[AwsBudgetsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSBUDGETS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AWS_BUDGETS,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Amazon Web Services (AWS Budgets)",
            iconPath="/static/services/aws_budgets.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
