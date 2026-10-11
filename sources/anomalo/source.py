from typing import cast

from sources.anomalo._config import AnomaloSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AnomaloSource(SimpleSource[AnomaloSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ANOMALO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ANOMALO,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Anomalo",
            iconPath="/static/services/anomalo.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
