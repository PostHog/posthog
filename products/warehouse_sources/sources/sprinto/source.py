from typing import cast

from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from products.warehouse_sources.sources.sprinto._config import SprintoSourceConfig


@SourceRegistry.register
class SprintoSource(SimpleSource[SprintoSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SPRINTO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SPRINTO,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Sprinto",
            iconPath="/static/services/sprinto.png",
            keywords=["compliance", "grc", "soc2", "audit", "security"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
