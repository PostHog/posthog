from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sprinto import (
    SprintoSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SprintoSource(SimpleSource[SprintoSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SPRINTO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SPRINTO,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Sprinto",
            iconPath="/static/services/sprinto.png",
            keywords=["compliance", "grc", "soc2", "audit", "security"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
