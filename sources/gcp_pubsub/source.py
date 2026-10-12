from typing import cast

from sources.gcp_pubsub._config import GcpPubsubSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GcpPubsubSource(SimpleSource[GcpPubsubSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPPUBSUB

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GCPPUBSUB,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Cloud Pub/Sub",
            iconPath="/static/services/gcp_pubsub.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
