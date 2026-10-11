from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

from sources.airbridge._config import AirbridgeSourceConfig


@SourceRegistry.register
class AirbridgeSource(SimpleSource[AirbridgeSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AIRBRIDGE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AIRBRIDGE,
            category=DataWarehouseSourceCategory.ADVERTISING,
            keywords=["mobile attribution", "mmp"],
            label="Airbridge",
            iconPath="/static/services/airbridge.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
