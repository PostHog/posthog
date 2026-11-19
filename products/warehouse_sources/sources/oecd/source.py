from typing import cast

from products.warehouse_sources.sources.oecd._config import OecdSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class OecdSource(SimpleSource[OecdSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OECD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.OECD,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="OECD (Organisation for Economic Co-operation and Development) Data API",
            iconPath="/static/services/oecd.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
