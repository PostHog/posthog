from typing import cast

from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from products.warehouse_sources.sources.thoughtspot._config import ThoughtspotSourceConfig


@SourceRegistry.register
class ThoughtspotSource(SimpleSource[ThoughtspotSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.THOUGHTSPOT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.THOUGHTSPOT,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="ThoughtSpot",
            iconPath="/static/services/thoughtspot.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
