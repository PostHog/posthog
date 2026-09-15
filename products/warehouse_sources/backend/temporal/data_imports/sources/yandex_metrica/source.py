from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.yandexmetrica import (
    YandexMetricaSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class YandexMetricaSource(SimpleSource[YandexMetricaSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.YANDEXMETRICA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.YANDEXMETRICA,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Yandex Metrica",
            iconPath="/static/services/yandex_metrica.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
