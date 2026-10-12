from typing import cast

from sources.outreach._config import OutreachSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class OutreachSource(SimpleSource[OutreachSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OUTREACH

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.OUTREACH,
            category=DataWarehouseSourceCategory.SALES,
            label="Outreach",
            iconPath="/static/services/outreach.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
