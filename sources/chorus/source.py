from typing import cast

from sources.chorus._config import ChorusSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class ChorusSource(SimpleSource[ChorusSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CHORUS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CHORUS,
            category=DataWarehouseSourceCategory.SALES,
            label="Chorus",
            iconPath="/static/services/chorus.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
