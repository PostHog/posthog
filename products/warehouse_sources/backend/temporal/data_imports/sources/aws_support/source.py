from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awssupport import (
    AwsSupportSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AwsSupportSource(SimpleSource[AwsSupportSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSSUPPORT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AWS_SUPPORT,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Amazon Web Services (AWS Support)",
            iconPath="/static/services/aws_support.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
