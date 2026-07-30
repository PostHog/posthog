from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    ConfluentCloudSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ConfluentCloudSource(SimpleSource[ConfluentCloudSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CONFLUENTCLOUD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CONFLUENT_CLOUD,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Confluent, Inc. (Confluent Cloud)",
            iconPath="/static/services/confluent_cloud.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
