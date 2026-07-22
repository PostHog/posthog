from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gcppubsub import (
    GcpPubsubSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GcpPubsubSource(SimpleSource[GcpPubsubSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPPUBSUB

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GCP_PUBSUB,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Cloud Pub/Sub",
            iconPath="/static/services/gcp_pubsub.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
