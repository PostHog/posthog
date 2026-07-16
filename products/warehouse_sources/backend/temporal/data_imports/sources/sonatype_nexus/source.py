from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SonatypeNexusSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SonatypeNexusSource(SimpleSource[SonatypeNexusSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SONATYPENEXUS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SONATYPE_NEXUS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Sonatype (Nexus Repository)",
            iconPath="/static/services/sonatype_nexus.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
