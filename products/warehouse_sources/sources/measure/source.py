from typing import cast

from products.warehouse_sources.sources.measure._config import MeasureSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceKey,
    SourceRegistry,
    source_key,
)

SOURCE_KEY = "Measure"


@SourceRegistry.register
class MeasureSource(SimpleSource[MeasureSourceConfig]):
    api_docs_url = "https://measure.sh/docs"

    @property
    def source_type(self) -> SourceKey:
        return source_key(SOURCE_KEY)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=self.source_type,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Measure",
            iconPath="/static/warehouse-sources/measure/icon.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
