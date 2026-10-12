from typing import cast

from sources.orbit._config import OrbitSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class OrbitSource(SimpleSource[OrbitSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ORBIT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ORBIT,
            category=DataWarehouseSourceCategory.CRM,
            label="Orbit",
            iconPath="/static/services/orbit.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
