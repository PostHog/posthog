from typing import cast

from products.warehouse_sources.sources.dropbox._config import DropboxSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class DropboxSource(SimpleSource[DropboxSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DROPBOX

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.DROPBOX,
            category=DataWarehouseSourceCategory.FILE_STORAGE,
            label="Dropbox",
            iconPath="/static/services/dropbox.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
