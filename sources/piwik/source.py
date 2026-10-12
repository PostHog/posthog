from typing import cast

from sources.piwik._config import PiwikSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class PiwikSource(SimpleSource[PiwikSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PIWIK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PIWIK,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Piwik",
            iconPath="/static/services/piwik.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
