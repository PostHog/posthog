from typing import cast

from sources.prestashop._config import PrestaShopSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class PrestaShopSource(SimpleSource[PrestaShopSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PRESTASHOP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PRESTASHOP,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="PrestaShop",
            iconPath="/static/services/prestashop.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
