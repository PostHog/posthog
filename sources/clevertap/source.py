from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

from sources.clevertap._config import ClevertapSourceConfig


@SourceRegistry.register
class ClevertapSource(SimpleSource[ClevertapSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLEVERTAP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CLEVERTAP,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="CleverTap",
            iconPath="/static/services/clevertap.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
