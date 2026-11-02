from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lettrlabs import (
    LettrLabsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LettrLabsSource(SimpleSource[LettrLabsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LETTRLABS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.LETTRLABS,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="LettrLabs",
            iconPath="/static/services/lettrlabs.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
