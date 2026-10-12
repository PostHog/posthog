from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.senseforce._config import SenseforceSourceConfig


@SourceRegistry.register
class SenseforceSource(SimpleSource[SenseforceSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SENSEFORCE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SENSEFORCE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Senseforce",
            iconPath="/static/services/senseforce.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
