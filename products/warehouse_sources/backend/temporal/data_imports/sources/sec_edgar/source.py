from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.secedgar import (
    SecEdgarSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SecEdgarSource(SimpleSource[SecEdgarSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SECEDGAR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SECEDGAR,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="SEC EDGAR",
            iconPath="/static/services/sec_edgar.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
