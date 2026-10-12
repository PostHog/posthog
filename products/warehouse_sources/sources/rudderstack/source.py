from typing import cast

from products.warehouse_sources.sources.rudderstack._config import RudderStackSourceConfig
from products.warehouse_sources.sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class RudderStackSource(SimpleSource[RudderStackSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RUDDERSTACK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.RUDDERSTACK,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="RudderStack",
            iconPath="/static/services/rudderstack.png",
            keywords=["cdp", "customer data platform", "event streaming"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
