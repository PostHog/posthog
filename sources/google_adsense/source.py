from typing import cast

from sources.google_adsense._config import GoogleAdSenseSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GoogleAdSenseSource(SimpleSource[GoogleAdSenseSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLEADSENSE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GOOGLEADSENSE,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Google AdSense",
            iconPath="/static/services/google_adsense.png",
            keywords=["adsense", "ads"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
