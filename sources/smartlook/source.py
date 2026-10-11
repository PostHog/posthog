from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.smartlook._config import SmartlookSourceConfig


@SourceRegistry.register
class SmartlookSource(SimpleSource[SmartlookSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SMARTLOOK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SMARTLOOK,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Smartlook (Smartlook.com s.r.o. / Cisco)",
            iconPath="/static/services/smartlook.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
