from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.heyreach import (
    HeyReachSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HeyReachSource(SimpleSource[HeyReachSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HEYREACH

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.HEYREACH,
            category=DataWarehouseSourceCategory.SALES,
            label="HeyReach",
            iconPath="/static/services/heyreach.png",
            keywords=["linkedin outreach", "sales engagement", "heyreach"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
