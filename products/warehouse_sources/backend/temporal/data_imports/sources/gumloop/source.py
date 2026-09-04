from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gumloop import (
    GumloopSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GumloopSource(SimpleSource[GumloopSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GUMLOOP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GUMLOOP,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Gumloop",
            iconPath="/static/services/gumloop.png",
            keywords=["automation", "workflow", "ai", "no-code"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
