from typing import cast

from sources.influxdb_cloud._config import InfluxdbCloudSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class InfluxdbCloudSource(SimpleSource[InfluxdbCloudSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.INFLUXDBCLOUD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.INFLUXDBCLOUD,
            category=DataWarehouseSourceCategory.DATABASES,
            label="InfluxData (InfluxDB Cloud)",
            iconPath="/static/services/influxdb_cloud.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
