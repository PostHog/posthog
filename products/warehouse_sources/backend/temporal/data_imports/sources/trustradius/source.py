from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.trustradius import (
    TrustradiusSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TrustradiusSource(SimpleSource[TrustradiusSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TRUSTRADIUS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TRUSTRADIUS,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="TrustRadius",
            iconPath="/static/services/trustradius.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
