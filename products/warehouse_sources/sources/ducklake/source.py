from typing import cast

from products.warehouse_sources.sources.ducklake._config import DuckLakeSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class DuckLakeSource(SimpleSource[DuckLakeSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DUCKLAKE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.DUCKLAKE,
            category=DataWarehouseSourceCategory.DATABASES,
            label="DuckLake",
            iconPath="/static/services/ducklake.png",
            keywords=["lakehouse", "data lake", "iceberg", "delta"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
