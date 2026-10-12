from typing import cast

from sources.kyve._config import KYVESourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class KYVESource(SimpleSource[KYVESourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KYVE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.KYVE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="KYVE",
            iconPath="/static/services/kyve.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
