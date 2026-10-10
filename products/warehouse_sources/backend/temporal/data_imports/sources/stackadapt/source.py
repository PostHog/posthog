from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.stackadapt import (
    StackAdaptSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class StackAdaptSource(SimpleSource[StackAdaptSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.STACKADAPT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.STACKADAPT,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="StackAdapt",
            iconPath="/static/services/stackadapt.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
