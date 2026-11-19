from typing import cast

from products.warehouse_sources.sources.adcell._config import AdcellSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceKey,
    SourceRegistry,
    source_key,
)

SOURCE_KEY = "Adcell"


@SourceRegistry.register
class AdcellSource(SimpleSource[AdcellSourceConfig]):
    api_docs_url = "https://www.adcell.de/api/v2/"

    @property
    def source_type(self) -> SourceKey:
        return source_key(SOURCE_KEY)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=self.source_type,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="ADCELL",
            iconPath="/static/warehouse-sources/adcell/icon.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
