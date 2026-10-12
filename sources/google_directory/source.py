from typing import cast

from sources.google_directory._config import GoogleDirectorySourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GoogleDirectorySource(SimpleSource[GoogleDirectorySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLEDIRECTORY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GOOGLEDIRECTORY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Directory",
            iconPath="/static/services/google_directory.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
