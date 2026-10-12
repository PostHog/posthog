from typing import cast

from sources.interzoid._config import InterzoidSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class InterzoidSource(SimpleSource[InterzoidSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.INTERZOID

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.INTERZOID,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Interzoid",
            iconPath="/static/services/interzoid.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
