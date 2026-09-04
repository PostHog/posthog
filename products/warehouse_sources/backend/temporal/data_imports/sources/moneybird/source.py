from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.moneybird import (
    MoneybirdSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MoneybirdSource(SimpleSource[MoneybirdSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MONEYBIRD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MONEYBIRD,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Moneybird",
            iconPath="/static/services/moneybird.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
