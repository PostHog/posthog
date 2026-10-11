from typing import cast

from sources.datascope._config import DatascopeSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class DatascopeSource(SimpleSource[DatascopeSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DATASCOPE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.DATASCOPE,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Datascope",
            iconPath="/static/services/datascope.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
