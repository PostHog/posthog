from typing import cast

from sources.mindbody._config import MindbodySourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class MindbodySource(SimpleSource[MindbodySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MINDBODY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MINDBODY,
            category=DataWarehouseSourceCategory.SALES,
            label="Mindbody, Inc.",
            iconPath="/static/services/mindbody.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
