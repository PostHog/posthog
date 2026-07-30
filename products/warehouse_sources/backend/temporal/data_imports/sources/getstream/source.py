from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GetStreamSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GetStreamSource(SimpleSource[GetStreamSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GETSTREAM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GET_STREAM,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Stream",
            iconPath="/static/services/getstream.png",
            keywords=["getstream", "chat", "activity feeds"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
