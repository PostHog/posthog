from typing import cast

from products.warehouse_sources.sources.sanity._config import SanitySourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class SanitySource(SimpleSource[SanitySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SANITY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SANITY,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Sanity",
            iconPath="/static/services/sanity.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
