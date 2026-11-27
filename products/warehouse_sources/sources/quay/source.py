from typing import cast

from products.warehouse_sources.sources.quay._config import QuaySourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class QuaySource(SimpleSource[QuaySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.QUAY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.QUAY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Red Hat Quay (quay.io)",
            iconPath="/static/services/quay.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
