from typing import cast

from products.warehouse_sources.sources.healthie._config import HealthieSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class HealthieSource(SimpleSource[HealthieSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HEALTHIE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.HEALTHIE,
            category=DataWarehouseSourceCategory.CRM,
            label="Healthie",
            iconPath="/static/services/healthie.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
