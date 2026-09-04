from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.appdirect import (
    AppdirectSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AppdirectSource(SimpleSource[AppdirectSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.APPDIRECT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.APPDIRECT,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="AppDirect",
            iconPath="/static/services/appdirect.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
