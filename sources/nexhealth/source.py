from typing import cast

from sources.nexhealth._config import NexhealthSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class NexhealthSource(SimpleSource[NexhealthSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NEXHEALTH

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.NEXHEALTH,
            category=DataWarehouseSourceCategory.CRM,
            label="NexHealth",
            iconPath="/static/services/nexhealth.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
