from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tiktokshop import (
    TiktokShopSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TiktokShopSource(SimpleSource[TiktokShopSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TIKTOKSHOP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TIKTOKSHOP,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="TikTok Shop (Open Platform / Partner Center)",
            iconPath="/static/services/tiktok_shop.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
