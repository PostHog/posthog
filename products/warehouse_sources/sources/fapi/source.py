from typing import cast

from products.warehouse_sources.sources.fapi._config import FapiSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceKey,
    SourceRegistry,
    source_key,
)

SOURCE_KEY = "Fapi"


@SourceRegistry.register
class FapiSource(SimpleSource[FapiSourceConfig]):
    api_docs_url = "https://web.fapi.cz/api-doc/"

    @property
    def source_type(self) -> SourceKey:
        return source_key(SOURCE_KEY)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=self.source_type,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="FAPI",
            iconPath="/static/warehouse-sources/fapi/icon.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
