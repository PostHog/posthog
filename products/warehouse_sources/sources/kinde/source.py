from typing import cast

from products.warehouse_sources.sources.kinde._config import KindeSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class KindeSource(SimpleSource[KindeSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KINDE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.KINDE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Kinde",
            iconPath="/static/services/kinde.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
