from typing import cast

from products.warehouse_sources.sources.frisbii._config import FrisbiiSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceKey,
    SourceRegistry,
    source_key,
)

SOURCE_KEY = "Frisbii"


@SourceRegistry.register
class FrisbiiSource(SimpleSource[FrisbiiSourceConfig]):
    api_docs_url = "https://docs.frisbii-transform.com/reference/quickstart"

    @property
    def source_type(self) -> SourceKey:
        return source_key(SOURCE_KEY)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=self.source_type,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Frisbii",
            iconPath="/static/warehouse-sources/frisbii/icon.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
