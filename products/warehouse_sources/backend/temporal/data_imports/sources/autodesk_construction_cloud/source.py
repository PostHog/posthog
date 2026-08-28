from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.autodeskconstructioncloud import (
    AutodeskConstructionCloudSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AutodeskConstructionCloudSource(SimpleSource[AutodeskConstructionCloudSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AUTODESKCONSTRUCTIONCLOUD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AUTODESK_CONSTRUCTION_CLOUD,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Autodesk Construction Cloud (ACC/BIM 360) via Autodesk Platform Services",
            iconPath="/static/services/autodesk_construction_cloud.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
