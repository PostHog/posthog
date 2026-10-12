from typing import cast

from sources.captain_data._config import CaptainDataSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class CaptainDataSource(SimpleSource[CaptainDataSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CAPTAINDATA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CAPTAINDATA,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Captain Data",
            iconPath="/static/services/captain_data.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
