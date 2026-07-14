from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import E2BSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class E2BSource(SimpleSource[E2BSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.E2B

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.E2_B,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="E2B",
            iconPath="/static/services/e2b.png",
            keywords=["sandbox", "ai agents", "code execution", "infrastructure"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
