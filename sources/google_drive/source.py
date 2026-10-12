from typing import cast

from sources.google_drive._config import GoogleDriveSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GoogleDriveSource(SimpleSource[GoogleDriveSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLEDRIVE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GOOGLEDRIVE,
            category=DataWarehouseSourceCategory.FILE_STORAGE,
            label="Google Drive",
            iconPath="/static/services/google_drive.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
