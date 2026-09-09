from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.schematic import (
    SchematicSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SchematicSource(SimpleSource[SchematicSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SCHEMATIC

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SCHEMATIC,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Schematic",
            keywords=["schematichq", "entitlements"],
            iconPath="/static/services/schematic.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
