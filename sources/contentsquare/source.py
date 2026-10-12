from typing import cast

from sources.contentsquare._config import ContentsquareSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class ContentsquareSource(SimpleSource[ContentsquareSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CONTENTSQUARE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CONTENTSQUARE,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Contentsquare",
            iconPath="/static/services/contentsquare.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
