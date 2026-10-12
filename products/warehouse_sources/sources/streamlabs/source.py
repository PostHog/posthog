from typing import cast

from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from products.warehouse_sources.sources.streamlabs._config import StreamlabsSourceConfig


@SourceRegistry.register
class StreamlabsSource(SimpleSource[StreamlabsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.STREAMLABS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.STREAMLABS,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            keywords=["twitch", "streaming"],
            label="Streamlabs",
            iconPath="/static/services/streamlabs.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
