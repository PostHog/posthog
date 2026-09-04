from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zellify import (
    ZellifySourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ZellifySource(SimpleSource[ZellifySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZELLIFY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ZELLIFY,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Zellify",
            iconPath="/static/services/zellify.png",
            keywords=["web2app", "attribution", "funnels"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
