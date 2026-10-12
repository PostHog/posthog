from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.yandex_metrica._config import YandexMetricaSourceConfig


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
