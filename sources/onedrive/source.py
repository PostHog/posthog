from typing import cast

from sources.onedrive._config import OneDriveSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class OneDriveSource(SimpleSource[OneDriveSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ONEDRIVE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ONEDRIVE,
            category=DataWarehouseSourceCategory.FILE_STORAGE,
            label="OneDrive",
            iconPath="/static/services/onedrive.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
