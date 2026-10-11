from typing import cast

from sources.cube_cloud._config import CubeCloudSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class CubeCloudSource(SimpleSource[CubeCloudSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CUBECLOUD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CUBECLOUD,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Cube Dev (Cube Cloud)",
            iconPath="/static/services/cube_cloud.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
