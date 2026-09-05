from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gojiberry import (
    GojiberrySourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GojiberrySource(SimpleSource[GojiberrySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOJIBERRY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GOJIBERRY,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Gojiberry",
            iconPath="/static/services/gojiberry.png",
            keywords=["survey", "surveys"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
