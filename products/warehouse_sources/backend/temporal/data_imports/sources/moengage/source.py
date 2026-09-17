from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.moengage import (
    MoEngageSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MoEngageSource(SimpleSource[MoEngageSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MOENGAGE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MOENGAGE,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="MoEngage",
            iconPath="/static/services/moengage.png",
            keywords=["push notifications", "customer engagement", "marketing automation", "moengage"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
