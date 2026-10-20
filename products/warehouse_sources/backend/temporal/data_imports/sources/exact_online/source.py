from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.exactonline import (
    ExactOnlineSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ExactOnlineSource(SimpleSource[ExactOnlineSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.EXACTONLINE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.EXACTONLINE,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Exact Online",
            iconPath="/static/services/exact_online.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
