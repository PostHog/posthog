from typing import cast

from sources.mercado_ads._config import MercadoAdsSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class MercadoAdsSource(SimpleSource[MercadoAdsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MERCADOADS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MERCADOADS,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Mercado Ads",
            iconPath="/static/services/mercado_ads.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
