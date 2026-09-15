from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.basecamp import (
    BasecampSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BasecampSource(SimpleSource[BasecampSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BASECAMP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.BASECAMP,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Basecamp",
            iconPath="/static/services/basecamp.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
