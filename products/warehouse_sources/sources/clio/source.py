from typing import cast

from products.warehouse_sources.sources.clio._config import ClioSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class ClioSource(SimpleSource[ClioSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLIO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CLIO,
            category=DataWarehouseSourceCategory.CRM,
            label="Clio",
            iconPath="/static/services/clio.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
