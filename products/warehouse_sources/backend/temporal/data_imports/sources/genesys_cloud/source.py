from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.genesyscloud import (
    GenesysCloudSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GenesysCloudSource(SimpleSource[GenesysCloudSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GENESYSCLOUD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GENESYS_CLOUD,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Genesys Cloud (Genesys Telecommunications Laboratories)",
            iconPath="/static/services/genesys_cloud.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
