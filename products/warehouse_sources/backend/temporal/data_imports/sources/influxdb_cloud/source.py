from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.influxdbcloud import (
    InfluxdbCloudSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class InfluxdbCloudSource(SimpleSource[InfluxdbCloudSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.INFLUXDBCLOUD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.INFLUXDB_CLOUD,
            category=DataWarehouseSourceCategory.DATABASES,
            label="InfluxData (InfluxDB Cloud)",
            iconPath="/static/services/influxdb_cloud.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
