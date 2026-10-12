from typing import cast

from sources.linnworks._config import LinnworksSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class LinnworksSource(SimpleSource[LinnworksSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LINNWORKS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.LINNWORKS,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Linnworks",
            iconPath="/static/services/linnworks.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
