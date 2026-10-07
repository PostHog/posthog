from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.scrunch import (
    ScrunchSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ScrunchSource(SimpleSource[ScrunchSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SCRUNCH

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SCRUNCH,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Scrunch",
            keywords=["ai search visibility", "aeo", "geo"],
            iconPath="/static/services/scrunch.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
