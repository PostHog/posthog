from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import LambdaLabsSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LambdaLabsSource(SimpleSource[LambdaLabsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LAMBDALABS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LAMBDA_LABS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Lambda",
            iconPath="/static/services/lambda_labs.png",
            keywords=["gpu", "cloud", "compute", "infrastructure"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
