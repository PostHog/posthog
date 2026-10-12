from typing import cast

from sources.google_ad_manager._config import GoogleAdManagerSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GoogleAdManagerSource(SimpleSource[GoogleAdManagerSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLEADMANAGER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GOOGLEADMANAGER,
            category=DataWarehouseSourceCategory.ADVERTISING,
            keywords=["gam"],
            label="Google Ad Manager",
            iconPath="/static/services/google_ad_manager.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
