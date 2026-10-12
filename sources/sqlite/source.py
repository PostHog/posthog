from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.sqlite._config import SQLiteSourceConfig


@SourceRegistry.register
class SQLiteSource(SimpleSource[SQLiteSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SQLITE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SQLITE,
            category=DataWarehouseSourceCategory.DATABASES,
            label="SQLite",
            iconPath="/static/services/sqlite.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
