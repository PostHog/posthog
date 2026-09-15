from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.boulevard import (
    BoulevardSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BoulevardSource(SimpleSource[BoulevardSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BOULEVARD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.BOULEVARD,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Boulevard (joinblvd)",
            iconPath="/static/services/boulevard.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
