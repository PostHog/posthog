from typing import cast

from products.warehouse_sources.sources.creem._config import CreemSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class CreemSource(SimpleSource[CreemSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CREEM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CREEM,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Creem",
            iconPath="/static/services/creem.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
