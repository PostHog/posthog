from typing import cast

from sources.schematic._config import SchematicSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class SchematicSource(SimpleSource[SchematicSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SCHEMATIC

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SCHEMATIC,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Schematic",
            keywords=["schematichq", "entitlements"],
            iconPath="/static/services/schematic.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
