from typing import cast

from sources.kickstarter._config import KickstarterSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class KickstarterSource(SimpleSource[KickstarterSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KICKSTARTER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.KICKSTARTER,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Kickstarter",
            iconPath="/static/services/kickstarter.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
