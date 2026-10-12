from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.uploadcare._config import UploadcareSourceConfig


@SourceRegistry.register
class UploadcareSource(SimpleSource[UploadcareSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.UPLOADCARE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.UPLOADCARE,
            category=DataWarehouseSourceCategory.FILE_STORAGE,
            label="Uploadcare",
            keywords=["uploadcare.com"],
            iconPath="/static/services/uploadcare.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
