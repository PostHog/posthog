from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.loopreturns import (
    LoopReturnsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LoopReturnsSource(SimpleSource[LoopReturnsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LOOPRETURNS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LOOP_RETURNS,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Loop Returns",
            iconPath="/static/services/loop_returns.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
