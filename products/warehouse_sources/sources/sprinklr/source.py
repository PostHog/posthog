from typing import cast

from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from products.warehouse_sources.sources.sprinklr._config import SprinklrSourceConfig


@SourceRegistry.register
class SprinklrSource(SimpleSource[SprinklrSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SPRINKLR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SPRINKLR,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Sprinklr",
            iconPath="/static/services/sprinklr.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
