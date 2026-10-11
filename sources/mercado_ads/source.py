from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

from sources.mercado_ads._config import MercadoAdsSourceConfig


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
