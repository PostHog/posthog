from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

from sources.airbyte._config import AirbyteSourceConfig


@SourceRegistry.register
class AirbyteSource(SimpleSource[AirbyteSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AIRBYTE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AIRBYTE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Airbyte",
            iconPath="/static/services/airbyte.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
