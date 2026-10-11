from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

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
