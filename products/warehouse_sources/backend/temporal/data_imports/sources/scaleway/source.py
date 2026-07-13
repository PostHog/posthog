from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ScalewaySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ScalewaySource(SimpleSource[ScalewaySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SCALEWAY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SCALEWAY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Scaleway",
            iconPath="/static/services/scaleway.png",
            keywords=["cloud", "billing", "infrastructure", "invoices"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
