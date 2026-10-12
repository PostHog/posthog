from typing import cast

from sources.appwrite._config import AppwriteSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AppwriteSource(SimpleSource[AppwriteSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.APPWRITE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.APPWRITE,
            category=DataWarehouseSourceCategory.DATABASES,
            label="Appwrite",
            iconPath="/static/services/appwrite.png",
            keywords=["baas", "backend", "database", "auth"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
