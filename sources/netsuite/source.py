from typing import cast

from sources.netsuite._config import NetSuiteSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class NetSuiteSource(SimpleSource[NetSuiteSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NETSUITE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.NETSUITE,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="NetSuite",
            iconPath="/static/services/netsuite.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
