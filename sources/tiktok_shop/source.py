from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.tiktok_shop._config import TiktokShopSourceConfig


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
