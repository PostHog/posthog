from typing import cast

from sources.salestrics._config import SalestricsSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class SalestricsSource(SimpleSource[SalestricsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SALESTRICS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SALESTRICS,
            category=DataWarehouseSourceCategory.CRM,
            label="Salestrics",
            iconPath="/static/services/salestrics.png",
            keywords=["crm", "sales"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
