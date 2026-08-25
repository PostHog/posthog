from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cleartax import (
    CleartaxSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CleartaxSource(SimpleSource[CleartaxSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLEARTAX

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CLEARTAX,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="ClearTax (Clear / Defmacro Software Pvt. Ltd.)",
            iconPath="/static/services/cleartax.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
