from typing import cast

from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from products.warehouse_sources.sources.wistia._config import WistiaSourceConfig


@SourceRegistry.register
class WistiaSource(SimpleSource[WistiaSourceConfig]):
    api_docs_url = "https://docs.wistia.com/reference/getting-started-with-the-data-api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WISTIA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.WISTIA,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Wistia",
            iconPath="/static/services/wistia.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
