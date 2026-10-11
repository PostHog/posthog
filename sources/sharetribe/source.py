from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.sharetribe._config import SharetribeSourceConfig


@SourceRegistry.register
class SharetribeSource(SimpleSource[SharetribeSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SHARETRIBE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SHARETRIBE,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Sharetribe",
            iconPath="/static/services/sharetribe.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
