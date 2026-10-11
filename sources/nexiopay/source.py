from typing import cast

from sources.nexiopay._config import NexiopaySourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class NexiopaySource(SimpleSource[NexiopaySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NEXIOPAY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.NEXIOPAY,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Nexiopay",
            iconPath="/static/services/nexiopay.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
