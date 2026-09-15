from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sharetribe import (
    SharetribeSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SharetribeSource(SimpleSource[SharetribeSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SHARETRIBE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SHARETRIBE,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Sharetribe",
            iconPath="/static/services/sharetribe.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
