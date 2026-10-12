from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.wps_office._config import WPSOfficeSourceConfig


@SourceRegistry.register
class WPSOfficeSource(SimpleSource[WPSOfficeSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WPSOFFICE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.WPSOFFICE,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="WPS Office",
            iconPath="/static/services/wps_office.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
