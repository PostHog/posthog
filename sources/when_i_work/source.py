from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.when_i_work._config import WhenIWorkSourceConfig


@SourceRegistry.register
class WhenIWorkSource(SimpleSource[WhenIWorkSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WHENIWORK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.WHENIWORK,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="When I Work",
            iconPath="/static/services/when_i_work.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
