from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.postnord import (
    PostNordSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PostNordSource(SimpleSource[PostNordSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.POSTNORD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.POSTNORD,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="PostNord",
            iconPath="/static/services/postnord.png",
            keywords=["shipping", "logistics", "parcel", "delivery"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
