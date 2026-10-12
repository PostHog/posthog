from typing import cast

from sources.redpanda_cloud._config import RedpandaCloudSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class RedpandaCloudSource(SimpleSource[RedpandaCloudSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.REDPANDACLOUD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.REDPANDACLOUD,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Redpanda Data (Redpanda Cloud)",
            iconPath="/static/services/redpanda_cloud.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
