from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.sleuth._config import SleuthSourceConfig


@SourceRegistry.register
class SleuthSource(SimpleSource[SleuthSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SLEUTH

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SLEUTH,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Sleuth",
            iconPath="/static/services/sleuth.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
