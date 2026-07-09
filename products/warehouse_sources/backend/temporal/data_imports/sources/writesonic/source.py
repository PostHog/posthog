from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import WritesonicSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class WritesonicSource(SimpleSource[WritesonicSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WRITESONIC

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.WRITESONIC,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Writesonic",
            iconPath="/static/services/writesonic.png",
            keywords=["seo", "geo", "ai visibility", "content marketing"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
