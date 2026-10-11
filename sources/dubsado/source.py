from typing import cast

from sources.dubsado._config import DubsadoSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class DubsadoSource(SimpleSource[DubsadoSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DUBSADO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.DUBSADO,
            category=DataWarehouseSourceCategory.CRM,
            label="Dubsado",
            iconPath="/static/services/dubsado.png",
            keywords=["dubsado crm", "invoicing", "client management"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
