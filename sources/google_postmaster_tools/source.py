from typing import cast

from sources.google_postmaster_tools._config import GooglePostmasterToolsSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GooglePostmasterToolsSource(SimpleSource[GooglePostmasterToolsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLEPOSTMASTERTOOLS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GOOGLEPOSTMASTERTOOLS,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Google Postmaster Tools",
            iconPath="/static/services/googlepostmastertools.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
