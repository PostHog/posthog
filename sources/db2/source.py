from typing import cast

from sources.db2._config import Db2SourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class Db2Source(SimpleSource[Db2SourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DB2

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.DB2,
            category=DataWarehouseSourceCategory.DATABASES,
            keywords=["ibm db2", "sql"],
            label="IBM Db2",
            iconPath="/static/services/db2.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
