from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType

from sources.getstream._config import GetStreamSourceConfig


@SourceRegistry.register
class GetStreamSource(SimpleSource[GetStreamSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GETSTREAM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GETSTREAM,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Stream",
            iconPath="/static/services/getstream.png",
            keywords=["getstream", "chat", "activity feeds"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
