from typing import cast

from products.warehouse_sources.sources.leantime._config import LeantimeSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class LeantimeSource(SimpleSource[LeantimeSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LEANTIME

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.LEANTIME,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Leantime",
            iconPath="/static/services/leantime.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
