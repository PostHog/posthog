from typing import cast

from sources.apptivo._config import ApptivoSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class ApptivoSource(SimpleSource[ApptivoSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.APPTIVO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.APPTIVO,
            category=DataWarehouseSourceCategory.CRM,
            label="Apptivo",
            iconPath="/static/services/apptivo.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
