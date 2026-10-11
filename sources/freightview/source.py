from typing import cast

from sources.freightview._config import FreightviewSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class FreightviewSource(SimpleSource[FreightviewSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FREIGHTVIEW

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.FREIGHTVIEW,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Freightview",
            iconPath="/static/services/freightview.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
