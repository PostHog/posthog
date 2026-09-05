from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cubecloud import (
    CubeCloudSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


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
