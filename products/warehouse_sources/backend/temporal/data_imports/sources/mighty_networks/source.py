from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mightynetworks import (
    MightyNetworksSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MightyNetworksSource(SimpleSource[MightyNetworksSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MIGHTYNETWORKS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MIGHTY_NETWORKS,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Mighty Networks",
            iconPath="/static/services/mighty_networks.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
