from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gem import GemSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GemSource(SimpleSource[GemSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GEM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GEM,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="Gem",
            iconPath="/static/services/gem.png",
            keywords=["ats", "recruiting", "hiring", "talent", "sourcing"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
